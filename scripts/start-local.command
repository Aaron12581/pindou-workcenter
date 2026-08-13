#!/usr/bin/env bash
set -euo pipefail
script_root="$(cd "$(dirname "$0")" && pwd)"
exec "$script_root/start-local.sh"
