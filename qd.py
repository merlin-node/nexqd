#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""NexKr 签到管理菜单  —  命令: qd"""

import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

VERSION = "1.1.0"
REPO = "merlin-node/nexqd"
REPO_ZIP = f"https://github.com/{REPO}/archive/refs/heads/main.zip"
REPO_RAW = f"https://raw.githubusercontent.com/{REPO}/main"
DIR = Path("/opt/nexqd")
DATA = DIR / "data"
CONF = DATA / "accounts.json"
STATUS = DATA / "status.json"
CONTAINER = "nexqd"
APP_FILES = ["Dockerfile", "docker-compose.yml", "requirements.txt", "app", "qd.py",
             "install.sh", "README.md"]
IMAGE = "ghcr.io/merlin-node/nexqd:latest"

DEFAULT_CONF = {
    "tg": {"bot_token": "", "user_id": ""},
    "schedule": {"time": "09:00", "random_delay_minutes": 5},
    "max_retry": 3,
    "update_url": REPO_ZIP,
    "accounts": [],
}

# ---------------- 显示 ----------------
G, R, Y, C, B, D, N = ("\033[32m", "\033[31m", "\033[33m", "\033[36m",
                       "\033[1m", "\033[2m", "\033[0m")
LINE = D + "─" * 32 + N


def clear():
    print("\033[2J\033[H", end="")


def title(t):
    clear()
    print(f"{C}{B}━━ {t} ━━{N}")


def ok(t):
    print(f"{G}✔ {t}{N}")


def bad(t):
    print(f"{R}✘ {t}{N}")


def warn(t):
    print(f"{Y}! {t}{N}")


def pause():
    try:
        input(f"\n{D}回车返回…{N}")
    except (EOFError, KeyboardInterrupt):
        pass


def ask(prompt, default=None, secret=False):
    hint = f" [{default}]" if default not in (None, "") else ""
    try:
        if secret:
            v = getpass.getpass(f"{prompt}{hint}: ")
        else:
            v = input(f"{prompt}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return v if v != "" else (default if default is not None else "")


def confirm(prompt, default=False):
    v = ask(f"{prompt} (y/n)", "y" if default else "n")
    return (v or "").lower() in ("y", "yes")


def choose(options, back="返回"):
    """options: [(key, 文字)],返回选中的 key"""
    for k, t in options:
        print(f" {B}{k}{N}. {t}")
    print(f" {B}0{N}. {back}")
    print(LINE)
    return ask("请选择") or "0"


def mask(s, keep=3):
    s = str(s or "")
    if not s:
        return f"{R}未设置{N}"
    if len(s) <= keep * 2:
        return s[0] + "****"
    return s[:keep] + "****" + s[-keep:]


def mask_email(e):
    if "@" not in e:
        return e
    u, d = e.split("@", 1)
    return (u[:3] + "***" if len(u) > 3 else u[0] + "***") + "@" + d


# ---------------- 配置 ----------------
def load():
    if not CONF.exists():
        save(json.loads(json.dumps(DEFAULT_CONF)))
    conf = json.loads(CONF.read_text(encoding="utf-8"))
    for k, v in DEFAULT_CONF.items():
        if k not in conf:
            conf[k] = json.loads(json.dumps(v))
        elif isinstance(v, dict):
            for kk, vv in v.items():
                conf[k].setdefault(kk, vv)
    return conf


def save(conf):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = CONF.with_suffix(".tmp")
    tmp.write_text(json.dumps(conf, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONF)


def status():
    try:
        return json.loads(STATUS.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------- Docker ----------------
def sh(cmd, quiet=False):
    kw = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL} if quiet else {}
    try:
        return subprocess.run(cmd, shell=isinstance(cmd, str), cwd=DIR, **kw).returncode
    except KeyboardInterrupt:
        print()
        return 130


def running():
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", CONTAINER],
                       capture_output=True, text=True)
    return r.stdout.strip() == "true"


def compose(*args):
    return sh(["docker", "compose", *args])


def pull_or_build():
    print("拉取最新镜像…")
    if compose("pull") != 0:
        warn("拉取失败,改为本地构建(几分钟)…")
        if compose("build") != 0:
            bad("构建失败")
            return False
    compose("up", "-d")
    sh("docker image prune -f", quiet=True)
    return True


def need_running():
    if running():
        return True
    warn("签到服务没在运行")
    if confirm("现在启动?", True):
        compose("up", "-d")
        return running()
    return False


def run_in_container(*args):
    if not need_running():
        return
    print(f"{D}(浏览器启动较慢,请耐心等待;Ctrl+C 只中断显示){N}\n")
    sh(["docker", "exec", "-it", CONTAINER, "python", "main.py", *args])


# ---------------- 账号显示 ----------------
RESULT_TXT = {"ok": f"{G}成功{N}", "already": f"{G}已签到{N}", "fail": f"{R}失败{N}"}


def acc_brief(i, a, st):
    sw = f"{G}● 自动签到{N}" if a.get("enabled") else f"{D}○ 不签到{N}"
    print(f" {B}{i}{N}. {B}{a['name']}{N}  {sw}")
    print(f"    {D}{mask_email(a['email'])}{N}")
    s = st.get("accounts", {}).get(a["id"])
    if s:
        line = f"    上次 {s['time'][5:16]} {RESULT_TXT.get(s['result'], s['result'])}"
        if s["result"] == "ok":
            line += f" +${s.get('gain', 0):.2f}"
        if s.get("balance") is not None:
            line += f" 余额 ${s['balance']:.2f}"
        print(line)
        if s["result"] == "fail" and s.get("error"):
            print(f"    {R}{s['error'][:60]}{N}")
    else:
        print(f"    {D}还没签到记录{N}")


def ask_email(conf, current=None):
    while True:
        e = ask("邮箱", current)
        if e is None:
            return None
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", e):
            bad("邮箱格式不对")
            continue
        if any(a["email"].lower() == e.lower() and a["email"] != current for a in conf["accounts"]):
            bad("这个邮箱已经添加过了")
            continue
        return e


def ask_password():
    while True:
        p = ask("密码(输入不显示)", secret=True)
        if p is None:
            return None
        if not p:
            bad("密码不能为空")
            continue
        p2 = ask("再输一次确认", secret=True)
        if p2 is None:
            return None
        if p != p2:
            bad("两次不一致,重新输入")
            continue
        return p


def clear_profile(aid):
    shutil.rmtree(DATA / "profiles" / aid, ignore_errors=True)


# ---------------- 1. 添加账号 ----------------
def add_account():
    conf = load()
    title("添加账号")
    print(f"{D}直接回车用 [] 里的默认值{N}\n")
    email = ask_email(conf)
    if email is None:
        return
    pw = ask_password()
    if pw is None:
        return
    name = ask("备注名称", email.split("@")[0])
    if any(a["name"] == name for a in conf["accounts"]):
        name = f"{name}-{len(conf['accounts']) + 1}"
    enabled = confirm("每天自动签到?", True)
    acc = {"id": uuid.uuid4().hex[:8], "name": name, "email": email,
           "password": pw, "enabled": enabled}
    conf["accounts"].append(acc)
    save(conf)
    print()
    ok(f"已添加 {name}")
    if confirm("现在签到一次测试?", True):
        run_in_container("run", "--id", acc["id"])
    pause()


# ---------------- 2. 账号管理 ----------------
def manage_accounts():
    while True:
        conf, st = load(), status()
        title("账号管理")
        if not conf["accounts"]:
            warn("还没有账号,先去添加")
            pause()
            return
        for i, a in enumerate(conf["accounts"], 1):
            acc_brief(i, a, st)
            print()
        print(LINE)
        v = ask("输入序号管理账号,0 返回") or "0"
        if v == "0":
            return
        if v.isdigit() and 1 <= int(v) <= len(conf["accounts"]):
            account_detail(conf["accounts"][int(v) - 1]["id"])


def account_detail(aid):
    while True:
        conf, st = load(), status()
        idx = next((i for i, a in enumerate(conf["accounts"]) if a["id"] == aid), None)
        if idx is None:
            return
        a = conf["accounts"][idx]
        title(f"账号:{a['name']}")
        print(f" 邮箱:{a['email']}")
        print(f" 密码:{mask(a['password'], 1)}")
        print(f" 自动签到:{G + '开启' if a.get('enabled') else R + '关闭'}{N}")
        print(LINE)
        toggle = "关闭自动签到" if a.get("enabled") else "开启自动签到"
        v = choose([("1", toggle), ("2", "修改邮箱"), ("3", "修改密码"),
                    ("4", "修改备注名"), ("5", "立即签到此账号"),
                    ("6", "清除登录状态(重新登录)"), ("7", f"{R}删除此账号{N}")])
        if v == "0":
            return
        if v == "1":
            a["enabled"] = not a.get("enabled")
            save(conf)
            ok(f"已{'开启' if a['enabled'] else '关闭'}自动签到")
        elif v == "2":
            e = ask_email(conf, a["email"])
            if e and e != a["email"]:
                a["email"] = e
                save(conf)
                clear_profile(aid)
                ok("邮箱已修改(已清除旧登录状态)")
        elif v == "3":
            p = ask_password()
            if p:
                a["password"] = p
                save(conf)
                clear_profile(aid)
                ok("密码已修改")
        elif v == "4":
            n = ask("新备注名", a["name"])
            if n:
                a["name"] = n
                save(conf)
                ok("已修改")
        elif v == "5":
            run_in_container("run", "--id", aid)
        elif v == "6":
            clear_profile(aid)
            ok("已清除,下次签到会重新登录")
        elif v == "7":
            if confirm(f"确定删除 {a['name']}?"):
                conf["accounts"].pop(idx)
                save(conf)
                clear_profile(aid)
                ok("已删除")
                pause()
                return
            continue
        else:
            continue
        pause()


# ---------------- 3. TG 配置 ----------------
def tg_send(token, uid, text):
    data = urllib.parse.urlencode({"chat_id": uid, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()).get("ok", False), ""
    except urllib.error.HTTPError as e:
        try:
            return False, json.loads(e.read()).get("description", str(e))
        except Exception:
            return False, str(e)
    except Exception as e:
        return False, str(e)


def tg_config():
    while True:
        conf = load()
        tg = conf["tg"]
        title("TG 推送配置")
        print(f" Bot Token:{mask(tg['bot_token'], 4)}")
        print(f" User ID :{tg['user_id'] or R + '未设置' + N}")
        print(LINE)
        print(f"{D} Token 找 @BotFather 创建 bot 获取")
        print(f" User ID 给 @userinfobot 发消息获取")
        print(f" 记得先给自己的 bot 发一次 /start{N}")
        print(LINE)
        v = choose([("1", "设置 Bot Token"), ("2", "设置 User ID"), ("3", "发送测试消息")])
        if v == "0":
            return
        if v == "1":
            t = ask("Bot Token")
            if t:
                if not re.match(r"^\d+:[\w-]{30,}$", t):
                    warn("格式看起来不太对,还是先保存了")
                tg["bot_token"] = t
                save(conf)
                ok("已保存")
        elif v == "2":
            u = ask("User ID", tg["user_id"])
            if u:
                if not re.match(r"^-?\d+$", u):
                    bad("User ID 应该是纯数字")
                else:
                    tg["user_id"] = u
                    save(conf)
                    ok("已保存")
        elif v == "3":
            if not tg["bot_token"] or not tg["user_id"]:
                bad("先把 Token 和 User ID 都填上")
            else:
                s, err = tg_send(tg["bot_token"], tg["user_id"],
                                 f"NexKr 签到推送测试 ✅\n{datetime.now():%Y-%m-%d %H:%M:%S}")
                ok("发送成功,去 TG 看看") if s else bad(f"发送失败:{err}")
        else:
            continue
        pause()


# ---------------- 4. 签到设置 ----------------
def schedule_config():
    while True:
        conf = load()
        sch = conf["schedule"]
        title("签到设置")
        print(f" 签到时间:每天 {B}{sch['time']}{N}")
        print(f" 随机延迟:0~{sch['random_delay_minutes']} 分钟")
        print(f" 失败重试:每轮 {conf['max_retry']} 次")
        print(f"{D} 一轮失败 1 小时后自动再补,每天最多 3 轮{N}")
        print(LINE)
        v = choose([("1", "修改签到时间"), ("2", "修改随机延迟"), ("3", "修改重试次数")])
        if v == "0":
            return
        if v == "1":
            t = ask("时间(24小时制 HH:MM)", sch["time"])
            m = re.match(r"^(\d{1,2})[:：](\d{2})$", t or "")
            if m and int(m[1]) < 24 and int(m[2]) < 60:
                sch["time"] = f"{int(m[1]):02d}:{m[2]}"
                save(conf)
                ok(f"已改为每天 {sch['time']},立即生效")
            else:
                bad("格式不对,例:09:00")
        elif v == "2":
            d = ask("最大随机延迟分钟(0~60)", str(sch["random_delay_minutes"]))
            if d and d.isdigit() and 0 <= int(d) <= 60:
                sch["random_delay_minutes"] = int(d)
                save(conf)
                ok("已保存")
            else:
                bad("请输入 0~60")
        elif v == "3":
            d = ask("每轮重试次数(1~5)", str(conf["max_retry"]))
            if d and d.isdigit() and 1 <= int(d) <= 5:
                conf["max_retry"] = int(d)
                save(conf)
                ok("已保存")
            else:
                bad("请输入 1~5")
        else:
            continue
        pause()


# ---------------- 5. 立即签到 ----------------
def run_all():
    conf = load()
    title("立即签到")
    on = [a for a in conf["accounts"] if a.get("enabled")]
    if not on:
        warn("没有开启自动签到的账号")
        pause()
        return
    print("将签到:" + "、".join(a["name"] for a in on) + "\n")
    if confirm("开始?", True):
        run_in_container("run")
    pause()


# ---------------- 6. 状态与日志 ----------------
def status_menu():
    while True:
        conf, st = load(), status()
        title("运行状态")
        r = running()
        print(f" 服务:{G + '● 运行中' if r else R + '● 已停止'}{N}")
        if st.get("plan"):
            print(f" 今日计划:{st['plan'][11:19]}")
        print(LINE)
        for i, a in enumerate(conf["accounts"], 1):
            acc_brief(i, a, st)
        print(LINE)
        v = choose([("1", "最近 50 行日志"), ("2", "实时日志(Ctrl+C 退出)"),
                    ("3", "重启服务"), ("4", "停止服务" if r else "启动服务")])
        if v == "0":
            return
        if v == "1":
            sh(["docker", "logs", "--tail", "50", CONTAINER])
        elif v == "2":
            sh(["docker", "logs", "-f", "--tail", "20", CONTAINER])
            continue
        elif v == "3":
            compose("restart")
        elif v == "4":
            compose("stop") if r else compose("up", "-d")
        else:
            continue
        pause()


# ---------------- 7. 更新 ----------------
def find_src(root):
    for p in [root, *root.rglob("*")]:
        if p.is_dir() and (p / "app" / "main.py").exists() and (p / "qd.py").exists():
            return p
    return None


def apply_update(src):
    for f in APP_FILES:
        s = src / f
        if not s.exists():
            continue
        d = DIR / f
        if s.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(s, d, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(s, d)
    os.chmod(DIR / "qd.py", 0o755)
    ok("脚本文件已更新")
    if pull_or_build():
        ok("更新完成,重新输入 qd 进入新版本")
    sys.exit(0)


def extract(path, tmp):
    if zipfile.is_zipfile(path):
        zipfile.ZipFile(path).extractall(tmp)
    elif tarfile.is_tarfile(path):
        tarfile.open(path).extractall(tmp)
    else:
        raise ValueError("不是 zip 或 tar.gz 文件")
    return find_src(Path(tmp))


def remote_version():
    try:
        with urllib.request.urlopen(f"{REPO_RAW}/qd.py", timeout=15) as r:
            m = re.search(r'VERSION = "([\d.]+)"', r.read().decode("utf-8", "ignore"))
            return m[1] if m else None
    except Exception:
        return None


def vtuple(v):
    return tuple(int(x) for x in v.split("."))


def update_from_url(url):
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "pkg"
        print("下载中…")
        urllib.request.urlretrieve(url, f)
        src = extract(f, Path(tmp) / "x")
        apply_update(src) if src else bad("下载的包里没找到脚本文件")


def update_menu():
    while True:
        conf = load()
        title("更新脚本")
        print(f" 当前版本:v{VERSION}")
        print(f"{D} 正在检查 GitHub…{N}", end="\r")
        rv = remote_version()
        if rv:
            new = vtuple(rv) > vtuple(VERSION)
            print(f" 最新版本:v{rv} {Y + '有更新' if new else G + '已是最新'}{N}")
        else:
            print(f" 最新版本:{R}检查失败{N}      ")
        print(f"{D} 仓库:github.com/{REPO}{N}")
        print(LINE)
        v = choose([("1", "从 GitHub 更新"), ("2", "从本地 zip 更新"),
                    ("3", "自定义下载地址更新"), ("4", "只拉取最新镜像(升级 Chrome)"),
                    ("5", "本地构建镜像(拉取失败时用)")])
        if v == "0":
            return
        try:
            if v == "1":
                if rv and not vtuple(rv) > vtuple(VERSION) and not confirm("已是最新,仍要重装?"):
                    continue
                update_from_url(REPO_ZIP)
            elif v == "2":
                p = ask("zip 路径", "/root/nexqd.zip")
                if not p or not Path(p).exists():
                    bad("文件不存在")
                else:
                    with tempfile.TemporaryDirectory() as tmp:
                        src = extract(p, tmp)
                        apply_update(src) if src else bad("压缩包里没找到脚本文件")
            elif v == "3":
                url = ask("下载地址(zip/tar.gz)", conf.get("update_url") or REPO_ZIP)
                if url:
                    conf["update_url"] = url
                    save(conf)
                    update_from_url(url)
            elif v == "4":
                pull_or_build() and ok("已是最新镜像")
            elif v == "5":
                if compose("build", "--pull") == 0:
                    compose("up", "-d")
                    ok("构建完成")
            else:
                continue
        except Exception as e:
            bad(f"更新失败:{e}")
        pause()


# ---------------- 8. 彻底删除 ----------------
def uninstall():
    title("彻底删除")
    print(f"{R}将删除:签到服务、Docker 镜像、")
    print(f"所有账号配置和登录状态、qd 命令{N}\n")
    if not confirm("确定要彻底删除?"):
        return
    if confirm("先备份账号配置?", True):
        bk = Path(f"/root/nexkr-backup-{datetime.now():%Y%m%d%H%M}.json")
        shutil.copy2(CONF, bk)
        ok(f"已备份到 {bk}")
    if (ask("输入 delete 确认") or "") != "delete":
        warn("已取消")
        pause()
        return
    compose("down", "--rmi", "all")
    shutil.rmtree(DIR, ignore_errors=True)
    for p in ("/usr/local/bin/qd",):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    ok("已全部删除,再见 👋")
    sys.exit(0)


# ---------------- 主菜单 ----------------
def main_menu():
    while True:
        conf = load()
        title(f"NexQD 签到管理 v{VERSION}")
        r = running()
        on = sum(1 for a in conf["accounts"] if a.get("enabled"))
        tg_ok = conf["tg"]["bot_token"] and conf["tg"]["user_id"]
        print(f" 服务:{G + '● 运行中' if r else R + '● 已停止'}{N}")
        print(f" 账号:{len(conf['accounts'])} 个,自动签到 {on} 个")
        print(f" 时间:每天 {conf['schedule']['time']}"
              f" (+0~{conf['schedule']['random_delay_minutes']}分)")
        print(f" 推送:{G + '已配置' if tg_ok else R + '未配置'}{N}")
        print(LINE)
        v = choose([("1", "添加账号"), ("2", "账号管理(查看/修改)"), ("3", "TG 推送配置"),
                    ("4", "签到设置"), ("5", "立即签到"), ("6", "运行状态/日志"),
                    ("7", "更新脚本"), ("8", f"{R}彻底删除{N}")], back="退出")
        actions = {"1": add_account, "2": manage_accounts, "3": tg_config,
                   "4": schedule_config, "5": run_all, "6": status_menu,
                   "7": update_menu, "8": uninstall}
        if v == "0":
            clear()
            return
        if v in actions:
            actions[v]()


if __name__ == "__main__":
    if os.geteuid() != 0:
        sys.exit("请用 root 运行 qd")
    if "--init" in sys.argv:
        load()
        sys.exit(0)
    try:
        main_menu()
    except KeyboardInterrupt:
        clear()
