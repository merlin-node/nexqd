#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NexKr 多账号自动签到(容器内运行)
  python main.py                 常驻调度
  python main.py run             立即签到所有开启的账号
  python main.py run --id ID     立即签到指定账号(忽略开关)
"""

import argparse
import fcntl
import json
import os
import random
import re
import shutil
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, date, timedelta
from pathlib import Path

import requests
from seleniumbase import SB

DATA = Path(os.getenv("DATA_DIR", "/data"))
CONF_FILE = DATA / "accounts.json"
STATUS_FILE = DATA / "status.json"
PROFILES = DATA / "profiles"
SHOTS = DATA / "shots"

BASE = "https://nexkr.sh"
DASH = f"{BASE}/app/dashboard"

FAIL_ROUNDS_PER_DAY = 3        # 失败后当天最多再补几轮
FAIL_RETRY_GAP = 3600          # 每轮间隔(秒)

CF_TITLE_MARKS = ("Just a moment", "请稍候", "Attention Required", "Checking")
CF_BODY_MARKS = ("Verify you are human", "确认您是真人", "正在验证", "Checking your browser",
                 "检查您的浏览器", "needs to review the security")


# ================= 基础 =================
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(f"[{now_str()}] {msg}", flush=True)


def load_conf():
    if not CONF_FILE.exists():
        return {"tg": {}, "schedule": {"time": "09:00", "random_delay_minutes": 5},
                "max_retry": 3, "accounts": []}
    conf = json.loads(CONF_FILE.read_text(encoding="utf-8"))
    conf.setdefault("tg", {})
    sch = conf.setdefault("schedule", {})
    sch.setdefault("time", "09:00")
    sch.setdefault("random_delay_minutes", 5)
    conf.setdefault("max_retry", 3)
    conf.setdefault("accounts", [])
    return conf


def acc_id(acc):
    return acc.get("id") or re.sub(r"[^\w.-]", "_", acc.get("name", "acc"))


@contextmanager
def file_lock(name, wait_msg=None):
    DATA.mkdir(parents=True, exist_ok=True)
    f = open(DATA / name, "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if wait_msg:
                log(wait_msg)
            fcntl.flock(f, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def read_status():
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def update_status(fn):
    with file_lock("status.lock"):
        st = read_status()
        st.setdefault("accounts", {})
        fn(st)
        tmp = STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, STATUS_FILE)


def get_pending(aid):
    """今天点签到前记下的余额(用于重试时还原本次获得)"""
    p = read_status().get("pending", {}).get(aid)
    return p if p and p.get("date") == date.today().isoformat() else None


def set_pending(aid, before):
    update_status(lambda st: st.setdefault("pending", {}).__setitem__(
        aid, {"date": date.today().isoformat(), "before": before}))


def clear_pending(aid):
    update_status(lambda st: st.setdefault("pending", {}).pop(aid, None))


def chrome_bin():
    if os.getenv("CHROME_BIN"):
        return os.getenv("CHROME_BIN")
    if not shutil.which("google-chrome") and shutil.which("chromium"):
        return shutil.which("chromium")
    return None


def tg_send(conf, text, photo=None):
    tg = conf.get("tg", {})
    token, uid = tg.get("bot_token"), tg.get("user_id")
    if not token or not uid:
        log("未配置 TG,跳过推送")
        return
    try:
        if photo and Path(photo).exists():
            with open(photo, "rb") as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                              data={"chat_id": uid, "caption": text[:1000]},
                              files={"photo": f}, timeout=30)
        else:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": uid, "text": text}, timeout=30)
    except Exception as e:
        log(f"TG 推送失败: {e}")


# ================= 过盾 =================
def full_page_challenge(sb):
    try:
        title = sb.get_title() or ""
        if any(m in title for m in CF_TITLE_MARKS):
            return True
        body = sb.get_text("body") or ""
        return len(body) < 800 and any(m in body for m in CF_BODY_MARKS)
    except Exception:
        return False


def turnstile_pending(sb):
    try:
        for el in sb.find_elements('input[name="cf-turnstile-response"]'):
            if not (el.get_attribute("value") or "").strip():
                return True
    except Exception:
        pass
    return False


def pass_shield(sb, tries=4):
    for i in range(tries):
        if not full_page_challenge(sb) and not turnstile_pending(sb):
            return
        log(f"检测到盾,模拟点击(第 {i + 1} 次)")
        try:
            sb.uc_gui_click_captcha()
        except Exception as e:
            log(f"点击验证出错: {e}")
        sb.sleep(5)
    if full_page_challenge(sb) or turnstile_pending(sb):
        raise RuntimeError("过盾失败")


def open_page(sb, url):
    sb.uc_open_with_reconnect(url, 4)
    sb.sleep(2)
    pass_shield(sb)


# ================= 页面操作 =================
def is_login_page(sb):
    return sb.is_element_present('input[type="password"]')


def first_visible(sb, selectors):
    for s in selectors:
        try:
            for el in sb.find_elements(s):
                if el.is_displayed():
                    return s, el
        except Exception:
            continue
    return None, None


def do_login(sb, acc):
    log("开始登录")
    _, email_el = first_visible(sb, [
        'input[type="email"]', 'input[name="email"]', 'input[autocomplete="email"]',
        'input[autocomplete="username"]', 'input[name="username"]', 'input[type="text"]'])
    if not email_el:
        raise RuntimeError("没找到邮箱输入框")
    email_el.clear()
    email_el.send_keys(acc["email"])
    pw = sb.find_element('input[type="password"]')
    pw.clear()
    pw.send_keys(acc["password"])
    sb.sleep(1)
    if turnstile_pending(sb):
        pass_shield(sb)

    sel, _ = first_visible(sb, [
        'button[type="submit"]',
        "//button[contains(normalize-space(.),'登录') or contains(.,'Login') or contains(.,'Sign in')]"])
    if not sel:
        raise RuntimeError("没找到登录按钮")
    sb.uc_click(sel, reconnect_time=4)
    sb.sleep(3)
    pass_shield(sb)

    for _ in range(30):
        if not is_login_page(sb) and "/app" in sb.get_current_url():
            break
        sb.sleep(1)
    else:
        raise RuntimeError("登录失败(邮箱/密码错误或被拦截)")
    if "/app/dashboard" not in sb.get_current_url():
        open_page(sb, DASH)
    log("登录成功")


def read_balance(sb):
    for _ in range(30):
        m = re.search(r"余额\s*\$?\s*([\d,]+(?:\.\d+)?)", sb.get_text("body") or "")
        if m:
            return float(m.group(1).replace(",", ""))
        sb.sleep(1)
    raise RuntimeError("没读到余额")


def already_signed(sb):
    return "已签到" in (sb.get_text("body") or "")


CHECKIN_XPATH = ("//button[contains(normalize-space(.),'签到') "
                 "and not(contains(normalize-space(.),'已签到'))]")


def click_checkin(sb):
    els = [e for e in sb.find_elements(CHECKIN_XPATH) if e.is_displayed()]
    if not els:
        return False
    els.sort(key=lambda e: 0 if e.text.strip() == "签到" else 1)
    btn = els[0]
    sb.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
    sb.sleep(1)
    log("点击签到按钮")
    try:
        btn.click()
    except Exception:
        sb.execute_script("arguments[0].click();", btn)
    return True


def wait_signed(sb, timeout=20):
    for _ in range(timeout):
        if already_signed(sb):
            return True
        if full_page_challenge(sb) or turnstile_pending(sb):
            pass_shield(sb)
        sb.sleep(1)
    return False


# ================= 单账号 =================
def checkin_once(acc):
    aid = acc_id(acc)
    profile = PROFILES / aid
    profile.mkdir(parents=True, exist_ok=True)
    for f in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            (profile / f).unlink()
        except Exception:
            pass
    SHOTS.mkdir(parents=True, exist_ok=True)
    shot = SHOTS / f"{aid}.png"

    with SB(uc=True, xvfb=True, locale_code="zh-CN",
            user_data_dir=str(profile), binary_location=chrome_bin()) as sb:
        try:
            open_page(sb, DASH)
            if not is_login_page(sb) and "/app" not in sb.get_current_url():
                open_page(sb, f"{BASE}/login")
            if is_login_page(sb):
                do_login(sb, acc)

            now_bal = read_balance(sb)
            pend = get_pending(aid)
            if already_signed(sb):
                if pend:
                    # 本轮之前的尝试其实已经签到成功,用当时记下的余额算本次获得
                    log(f"之前的尝试已签到成功,签到前余额 ${pend['before']:.2f}")
                    return {"result": "ok", "before": pend["before"], "after": now_bal}
                return {"result": "already", "before": now_bal, "after": now_bal}

            before = now_bal
            log(f"签到前余额 ${before:.2f}")
            set_pending(aid, before)
            if not click_checkin(sb):
                raise RuntimeError("没找到签到按钮")
            wait_signed(sb, 15)

            # 刷新页面确认结果(余额可能稍后才更新)
            after, signed = before, False
            for _ in range(6):
                sb.sleep(2)
                open_page(sb, DASH)
                after = read_balance(sb)
                signed = already_signed(sb)
                if signed and after != before:
                    break
            if not signed and after == before:
                raise RuntimeError("点了签到但页面和余额都没变化")
            log(f"签到后余额 ${after:.2f}")
            return {"result": "ok", "before": before, "after": after}
        except Exception:
            try:
                sb.driver.save_screenshot(str(shot))
            except Exception:
                pass
            raise


def run_account(conf, acc, final_round=True):
    aid, name = acc_id(acc), acc.get("name", acc.get("email"))
    retry = int(conf.get("max_retry", 3))
    err = ""
    log(f"===== 账号 {name} =====")
    for attempt in range(1, retry + 1):
        try:
            log(f"第 {attempt}/{retry} 次尝试")
            r = checkin_once(acc)
            gain = r["after"] - r["before"]
            if r["result"] == "ok":
                msg = (f"NexKr 签到成功 ✔️\n\n账号:{name}\n\n"
                       f"本次获得:${gain:.2f}\n\n"
                       f"签到前余额:${r['before']:.2f}\n\n"
                       f"当前余额:${r['after']:.2f}")
            else:
                msg = (f"NexKr 今天已签到 ℹ️\n\n账号:{name}\n\n"
                       f"当前余额:${r['after']:.2f}")
            tg_send(conf, msg)
            log(msg.replace("\n\n", " | "))

            def ok(st):
                st["accounts"][aid] = {"date": date.today().isoformat(), "time": now_str(),
                                       "result": r["result"], "gain": round(gain, 2),
                                       "balance": r["after"], "rounds": 0, "error": ""}
            update_status(ok)
            clear_pending(aid)
            return True
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            log(traceback.format_exc())
            if attempt < retry:
                time.sleep(15)

    def fail(st):
        old = st["accounts"].get(aid, {})
        rounds = old.get("rounds", 0) + 1 if old.get("date") == date.today().isoformat() else 1
        st["accounts"][aid] = {**old, "date": date.today().isoformat(), "time": now_str(),
                               "result": "fail", "rounds": rounds, "error": err}
    update_status(fail)
    rounds = read_status()["accounts"][aid]["rounds"]
    tip = "今天不再重试" if rounds >= FAIL_ROUNDS_PER_DAY or final_round else "1 小时后自动重试"
    tg_send(conf, f"NexKr 签到失败 ❌\n\n账号:{name}\n\n错误:{err}\n\n{tip}",
            photo=SHOTS / f"{aid}.png")
    return False


def run_accounts(conf, accounts, final_round=True):
    with file_lock("run.lock", wait_msg="有其他签到任务在跑,排队等待…"):
        for i, acc in enumerate(accounts):
            if i > 0:
                gap = random.randint(20, 60)
                log(f"等待 {gap} 秒后跑下一个账号")
                time.sleep(gap)
            run_account(conf, acc, final_round)


# ================= 调度 =================
def due_accounts(conf):
    st = read_status().get("accounts", {})
    today = date.today().isoformat()
    todo = []
    for a in conf["accounts"]:
        if not a.get("enabled"):
            continue
        s = st.get(acc_id(a), {})
        if s.get("date") != today:
            todo.append(a)
        elif s.get("result") == "fail" and s.get("rounds", 0) < FAIL_ROUNDS_PER_DAY:
            last = datetime.strptime(s["time"], "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - last).total_seconds() >= FAIL_RETRY_GAP:
                todo.append(a)
    return todo


def scheduler():
    log("调度器启动")
    plan_key, plan_at = None, None
    while True:
        try:
            conf = load_conf()
            sch = conf["schedule"]
            key = (date.today().isoformat(), sch["time"], sch["random_delay_minutes"])
            if key != plan_key:
                h, m = map(int, sch["time"].split(":"))
                delay = random.randint(0, int(sch["random_delay_minutes"]) * 60)
                plan_at = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0) \
                    + timedelta(seconds=delay)
                plan_key = key
                update_status(lambda st: st.update(plan=plan_at.strftime("%Y-%m-%d %H:%M:%S")))
                log(f"今日计划签到时间 {plan_at:%H:%M:%S}")

            if datetime.now() >= plan_at:
                todo = due_accounts(conf)
                if todo:
                    run_accounts(conf, todo, final_round=False)
        except Exception:
            log(traceback.format_exc())
        time.sleep(30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="daemon", choices=["daemon", "run"])
    ap.add_argument("--id", help="只跑这个账号 id")
    args = ap.parse_args()

    if args.cmd == "daemon":
        scheduler()
        return
    conf = load_conf()
    if args.id:
        accs = [a for a in conf["accounts"] if acc_id(a) == args.id]
        if not accs:
            raise SystemExit("找不到这个账号")
    else:
        accs = [a for a in conf["accounts"] if a.get("enabled")]
        if not accs:
            raise SystemExit("没有开启自动签到的账号")
    run_accounts(conf, accs)


if __name__ == "__main__":
    main()
