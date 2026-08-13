#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
api_root="$project_root/services/api"
venv_root="$api_root/.venv"

for required_port in 8000 3000; do
  if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:"$required_port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "错误：端口 $required_port 已被旧进程占用。请先关闭之前启动拼豆工作台的终端窗口，再重新双击本脚本。" >&2
    exit 1
  fi
done

echo "正在启动拼豆工作台 v0.20.52（批量擦除拖拽修复版）"

if [[ ! -f "$project_root/scripts/serve-production.mjs" || ! -f "$project_root/dist/server/index.js" ]]; then
  echo "错误：本安装包的正式前端运行文件不完整。请重新完整解压 v0.20.49 安装包后再启动。" >&2
  exit 1
fi

cd "$api_root"
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "错误：本地应用需要 Python 3.10 或更高版本（推荐 Python 3.12）。" >&2
  echo "当前 python3: $(python3 --version 2>&1 || echo '未安装')" >&2
  exit 1
fi
if [[ ! -x "$venv_root/bin/python" ]]; then
  python3 -m venv "$venv_root"
  "$venv_root/bin/pip" install -r requirements.txt
fi
if ! "$venv_root/bin/python" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "错误：现有 services/api/.venv 使用旧版 Python。请删除该 .venv 后重新启动。" >&2
  exit 1
fi

mkdir -p "$api_root/.data/uploads" "$api_root/.data/backups"
cd "$api_root"
"$venv_root/bin/uvicorn" app.main:app --host 127.0.0.1 --port 8000 &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT INT TERM

cd "$project_root"
export NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:8000"
export NODE_ENV=production
echo "正在启动已构建的正式前端：无需 npm 下载，也不会使用 Vite、Rollup 或 vinext。"
(sleep 3; open "http://127.0.0.1:3000/?version=0.20.52" >/dev/null 2>&1 || true) &
node "$project_root/scripts/serve-production.mjs"
