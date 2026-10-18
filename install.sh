#!/usr/bin/env bash
# NexQD 一键安装:
#   bash <(curl -fsSL https://raw.githubusercontent.com/merlin-node/nexqd/main/install.sh)
set -e
REPO="merlin-node/nexqd"
DIR=/opt/nexqd
OLD=/opt/nexkr-checkin

[ "$(id -u)" = 0 ] || { echo "请用 root 运行"; exit 1; }

echo "==> 检查依赖"
command -v python3 >/dev/null || { apt-get update; apt-get install -y python3; }
command -v curl >/dev/null || { apt-get update; apt-get install -y curl; }
if ! command -v docker >/dev/null; then
  echo "==> 安装 Docker"
  curl -fsSL https://get.docker.com | sh
fi
docker compose version >/dev/null 2>&1 || apt-get install -y docker-compose-plugin
systemctl enable --now docker >/dev/null 2>&1 || true

# 找源文件:脚本旁边有就用,没有就从 GitHub 下载
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
if [ ! -f "$SRC/app/main.py" ]; then
  echo "==> 从 GitHub 下载"
  TMP="$(mktemp -d)"
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.zip" -o "$TMP/pkg.zip"
  python3 -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$TMP/pkg.zip" "$TMP"
  SRC="$(dirname "$(find "$TMP" -path '*/app/main.py' | head -n1)")/.."
  SRC="$(cd "$SRC" && pwd)"
fi

echo "==> 安装到 $DIR"
mkdir -p "$DIR/data"
if [ "$SRC" != "$DIR" ]; then
  rm -rf "$DIR/app"
  for f in Dockerfile docker-compose.yml requirements.txt app qd.py install.sh README.md; do
    [ -e "$SRC/$f" ] && cp -r "$SRC/$f" "$DIR/"
  done
fi

# 迁移旧版(nexkr-checkin)
if [ -d "$OLD" ]; then
  echo "==> 发现旧版,迁移数据"
  (cd "$OLD" && docker compose down --rmi all >/dev/null 2>&1) || true
  [ -f "$DIR/data/accounts.json" ] || cp -a "$OLD/data/." "$DIR/data/" 2>/dev/null || true
  rm -rf "$OLD"
fi
docker rm -f nexkr-checkin nexqd >/dev/null 2>&1 || true

chmod +x "$DIR/qd.py" "$DIR/install.sh"
python3 "$DIR/qd.py" --init
chmod 700 "$DIR/data"
ln -sf "$DIR/qd.py" /usr/local/bin/qd

echo "==> 拉取镜像"
cd "$DIR"
if ! docker compose pull; then
  echo "==> 拉取失败,改为本地构建(要几分钟)"
  docker compose build
fi
docker compose up -d

echo
echo "✅ 安装完成!输入 qd 回车进入管理菜单"
