#!/usr/bin/env bash
set -euo pipefail

# Run this script on an Apple Silicon Mac.  The finished DMG contains no npm
# cache, Node modules, virtual environment, or Terminal launcher.
project_root="$(cd "$(dirname "$0")/.." && pwd)"
desktop_root="$project_root/desktop"
runtime_root="$desktop_root/runtime"
venv_root="$project_root/.desktop-build-venv"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "请在 Apple Silicon Mac 上构建此 DMG。" >&2
  exit 2
fi

cd "$project_root"
npm ci
NEXT_PUBLIC_API_BASE_URL="http://127.0.0.1:18080" npm run build

mkdir -p "$runtime_root/frontend/scripts" "$runtime_root/backend"
cp -R dist "$runtime_root/frontend/dist"
cp scripts/serve-production.mjs "$runtime_root/frontend/scripts/serve-production.mjs"

python3 -m venv "$venv_root"
"$venv_root/bin/pip" install --upgrade pip
"$venv_root/bin/pip" install -r services/api/requirements.txt pyinstaller
"$venv_root/bin/pyinstaller" --noconfirm --clean --onefile \
  --name perler-api \
  --paths services/api \
  --collect-all certifi \
  --collect-all PIL \
  --distpath "$runtime_root/backend" \
  desktop/api_bootstrap.py

cd "$desktop_root"
npm install
npm run dist:mac
