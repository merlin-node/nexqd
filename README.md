# NexQD

NexKr(nexkr.sh)多账号每日自动签到,Docker 部署,Telegram 推送结果。

- 真实 Chrome(SeleniumBase UC 模式 + Xvfb),遇到 Cloudflare 盾自动模拟点击
- 多账号,每个账号可单独开关自动签到
- 每天定时签到(默认 09:00 + 随机 0~5 分钟),失败 1 小时后自动补签,每天最多 3 轮
- `qd` 命令进入管理菜单

## 一、安装

适用 Debian / Ubuntu,用 root 登录 VPS,复制这一行回车:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/merlin-node/nexqd/main/install.sh)
```

首次安装 3~10 分钟,看到 `✅ 安装完成` 即可。然后输入:

```bash
qd
```

## 二、首次配置

1. 主菜单 `3` → TG 推送配置
   - `1` 填 Bot Token(TG 找 @BotFather 发 /newbot 获取)
   - `2` 填 User ID(TG 找 @userinfobot 获取)
   - 先在 TG 里给自己的 bot 点一次 Start
   - `3` 发测试消息,收到就对了
2. 主菜单 `1` → 添加账号,按提示填邮箱、密码,最后可以立即测试签到

## 三、菜单说明

```
1. 添加账号
2. 账号管理(查看/修改)
   └ 选序号:开关自动签到 / 改邮箱 / 改密码 /
     改备注 / 立即签到 / 清除登录状态 / 删除
3. TG 推送配置
4. 签到设置(时间 / 随机延迟 / 重试次数)
5. 立即签到
6. 运行状态/日志
7. 更新脚本(自动检查 GitHub 新版本)
8. 彻底删除
0. 退出
```

所有修改立即生效,不用重启。

## 四、换机器

**旧机器:备份配置**(账号、密码、TG 配置都在这一个文件里)

```bash
cat /opt/nexqd/data/accounts.json
```

把输出的全部内容复制,存到 Bitwarden 安全笔记里。里面有明文密码,不要发给别人。

**新机器:**

1. 按「一、安装」装好
2. 打开配置文件:

   ```bash
   nano /opt/nexqd/data/accounts.json
   ```

3. 删掉里面原有内容(按住 `Ctrl+K` 一行行删),粘贴备份的内容
4. `Ctrl+O` 回车保存,`Ctrl+X` 退出
5. 输入 `qd`,看账号是否都在,选 `5` 立即签到测试一次

不想备份的话,新机器上用 `qd` 重新添加账号也一样。

**旧机器:删除**

`qd` → `8` 彻底删除。

## 五、常见问题

| 现象 | 处理 |
|---|---|
| 签到失败,TG 收到截图 | `qd` → `2` → 选账号 → 清除登录状态,再立即签到试试 |
| 改了密码登录失败 | `qd` → `2` → 选账号 → 修改密码 |
| 推送收不到 | 确认给 bot 点过 Start,`qd` → `3` → `3` 测试 |
| 想看具体报错 | `qd` → `6` → `1` 查看日志 |

## 文件位置

- 程序:`/opt/nexqd`
- 配置:`/opt/nexqd/data/accounts.json`(仅 root 可读,`.gitignore` 已排除,不会上传仓库)
- 登录状态:`/opt/nexqd/data/profiles/`
- 失败截图:`/opt/nexqd/data/shots/`
