#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${SITES_ENV_READY:-}" != "1" ]]; then
  exec "${script_dir}/sites-env.sh" -- "$0" "$@"
fi

worker="${SITES_PROJECT_ROOT}/dist/server/index.js"
hosting="${SITES_PROJECT_ROOT}/dist/.openai/hosting.json"

[[ -f "${worker}" ]] || {
  echo "Missing Sites Worker entry: dist/server/index.js" >&2
  exit 66
}
[[ -f "${hosting}" ]] || {
  echo "Missing packaged Sites manifest: dist/.openai/hosting.json" >&2
  exit 66
}

node --input-type=module - "${worker}" "${hosting}" <<'NODE'
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

const [workerPath, hostingPath] = process.argv.slice(2);
JSON.parse(await readFile(hostingPath, "utf8"));

const workerUrl = pathToFileURL(workerPath);
workerUrl.searchParams.set("sites-validation", `${process.pid}-${Date.now()}`);
const worker = await import(workerUrl.href);
if (!worker.default || typeof worker.default.fetch !== "function") {
  throw new Error("dist/server/index.js must have an ESM default export with fetch(request, env, ctx)");
}
NODE

# UI-baseline gate: version histories are compact work-area popovers. A later
# feature fix must never reintroduce the rejected sidebar or inline-card UI.
page_source="${SITES_PROJECT_ROOT}/app/page.tsx"
style_source="${SITES_PROJECT_ROOT}/app/globals.css"
for required in 'function StageVersionMenu' 'stage="twod" label="2D"' 'stage="board" label="图板规划"' 'stage="pattern" label="图纸"'; do
  grep -Fq "$required" "$page_source" || { echo "Version UI baseline missing: $required" >&2; exit 67; }
done
for forbidden in 'StageHistoryPanel' 'stage-history-panel' '右侧独立版本记录'; do
  if grep -Fq "$forbidden" "$page_source" "$style_source"; then
    echo "Rejected version UI has reappeared: $forbidden" >&2
    exit 67
  fi
done
grep -Fq '.stage-version-popover{' "$style_source" || { echo "Version UI popover style is missing" >&2; exit 67; }

echo "Validated Sites artifact: ESM Worker default.fetch and hosting manifest are present."
