import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const developmentPreviewMeta =
  /<meta(?=[^>]*\bname=["']codex-preview["'])(?=[^>]*\bcontent=["']development["'])[^>]*>/i;

test("renders development preview metadata", async () => {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  const response = await worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );

  assert.equal(response.status, 200);
  assert.match(
    response.headers.get("content-type") ?? "",
    /^text\/html\b/i,
  );
  assert.match(await response.text(), developmentPreviewMeta);
});

test("includes advanced grid editing controls", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  for (const label of ["框选", "批量擦除", "复制", "平移", "显示色号", "显示坐标", "显示标线", "显示分板线"]) {
    assert.match(source, new RegExp(label));
  }
  assert.match(source, /copySelection/);
  assert.match(source, /moveSelection/);
  assert.match(source, /boardId:/);
});

test("batch erase clears a dragged rectangle as one undoable edit", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const board = source.slice(source.indexOf("function PatternBoard"), source.indexOf("export default function Home"));
  assert.match(board, /const eraseSelection/);
  assert.match(board, /tool === "批量擦除"/);
  assert.match(board, /next\.delete\(`\$\{x\}:\$\{y\}`\)/);
  assert.match(board, /onBatchErase\?\.\(erased, draft\)/);
  assert.match(board, /eraseSelection: \(\) => eraseSelection\(\)/);
});

test("exposes one-or-three finished 2D generation controls", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  for (const label of ["本次生成", "1 张", "3 张", "OpenAI", "MODEL_CONNECTION_FAILED"]) {
    assert.match(source, new RegExp(label.replace(".", "\\.")));
  }
  assert.match(source, /candidateMode === "single"/);
  assert.match(source, /ApiError/);
});

test("2D generation can retry model status instead of silently disabling its button", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const twoDStage = source.slice(
    source.indexOf("function TwoDStage"),
    source.indexOf("function BoardStage"),
  );
  assert.match(twoDStage, /const refreshModelStatus = async/);
  assert.match(twoDStage, /await refreshModelStatus\(\)/);
  assert.match(twoDStage, /暂时无法读取模型状态；点击生成时会自动重试/);
  assert.match(twoDStage, /disabled=\{busy \|\| !source\}/);
  assert.doesNotMatch(twoDStage, /disabled=\{busy \|\| !source \|\| !modelStatus\?\.configured\}/);
});

test("direct 2D import keeps its next-step action inside a viewport-bound 2D workspace", async () => {
  const [page, css] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /direct-import-footer/);
  assert.match(page, /已导入正式 2D/);
  assert.match(page, /进入图板规划/);
  assert.match(css, /\.twod-stage\{[^}]*height:calc\(100vh - 66px\)[^}]*overflow:hidden/);
  assert.match(css, /\.candidate-footer\{[^}]*flex:0 0 auto/);
  assert.match(css, /\.candidate-list\{[^}]*overflow:auto/);
});

test("uses current project data, real material preview controls and 52-pin boards", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(source, /projectOriginal/);
  assert.match(source, /projectTwoD/);
  assert.match(source, /project\?\.name \|\| "未打开项目"/);
  assert.match(source, /previewMode/);
  assert.match(source, /cropActive/);
  assert.match(source, /custom-board-editor/);
  assert.match(source, /custom_\$\{customCols\}x\$\{customRows\}/);
  assert.match(source, /单板 52×52/);
  assert.doesNotMatch(source, /defaultValue="可爱水果系列"/);
});

test("pattern generation uses the confirmed 2D and carries the selected board layout forward", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const patternStage = source.slice(
    source.indexOf("function PatternCandidateStage"),
    source.indexOf("function TwoDStage"),
  );
  assert.match(patternStage, /asset\.id === activeSourceAssetId && asset\.role === "confirmed_2d"/);
  assert.doesNotMatch(patternStage, /project\?\.assets\?\.\[0\]/);
  assert.match(patternStage, /useState\(boardLayout \|\| "single"\)/);
  assert.match(patternStage, /customBoardLabel/);
  assert.match(patternStage, /当前素材已应用的自定义组合/);
  assert.match(source, /setBoardLayout\(apiByLayout\[item\.id\]\)/);
});

test("keeps applied custom board plans available in the pattern stage for each formal 2D asset", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const patternStage = source.slice(
    source.indexOf("function PatternCandidateStage"),
    source.indexOf("function TwoDStage"),
  );
  assert.match(source, /BOARD_PLAN_STORAGE_KEY/);
  assert.match(source, /boardPlanStorageKey/);
  assert.match(source, /perler-board-plans-v1/);
  assert.match(source, /availableCustomLayouts/);
  assert.match(patternStage, /selectableCustomLayouts\.map/);
  assert.match(patternStage, /setBoardLayout\(next\)/);
  assert.match(patternStage, /const restoredLayout = hasSavedBoardPlan/);
  assert.match(patternStage, /当前素材已应用的自定义组合/);
});

test("pattern generation UI exposes an explicit local-or-model generation choice", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const patternStage = source.slice(
    source.indexOf("function PatternCandidateStage"),
    source.indexOf("function TwoDStage"),
  );
  assert.match(patternStage, /图纸生成方式/);
  assert.match(patternStage, /本地引擎/);
  assert.match(patternStage, /大模型直出/);
  assert.match(patternStage, /generationMode/);
  assert.match(patternStage, /v0\.19\.1 基线/);
  assert.doesNotMatch(patternStage, /比较 2D 与图纸初稿/);
});

test("formal 2D confirmation lets a Qwen candidate reach local repair, then refreshes and advances", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const confirmFlow = source.slice(
    source.indexOf("const confirm = async () =>"),
    source.indexOf("const markMask =", source.indexOf("const confirm = async () =>")),
  );
  assert.match(confirmFlow, /confirmTwoDCandidate/);
  assert.match(confirmFlow, /generationMode === "model_generated"/);
  assert.doesNotMatch(confirmFlow, /if \(!selected\.quality\?\.confirmable\) \{/);
  assert.match(confirmFlow, /getProject/);
  assert.match(confirmFlow, /onNext\(\)/);
  assert.match(confirmFlow, /setBusy\(true\)/);
  assert.match(confirmFlow, /setBusy\(false\)/);
  assert.match(confirmFlow, /候选确认失败/);
  assert.match(source, /disabled=\{busy \|\| !canAttemptConfirm\}/);
  assert.match(source, /正在本地确认/);
});

test("keeps every stage version control in its work-area header", async () => {
  const source = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
  for (const label of ["sidebarCollapsed", "StageVersionMenu", "保存当前{label}版本", "历史${label}版本", "导出当前 2D", "按当前设置重新生成", "色号-数量", "bounds={bounds}"]) {
    assert.match(source, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.doesNotMatch(source, /StageHistoryPanel/);
  assert.doesNotMatch(source, /stage-history-panel/);
  assert.doesNotMatch(source, /右侧独立版本记录/);
  assert.match(css, /\.stage-version-popover\{/);
  assert.doesNotMatch(css, /\.stage-history-panel/);
  assert.match(css, /\.pattern-cell\.filled\{background:var\(--bead\)\}/);
  assert.match(css, /\.planning-board\.fit-cover>img\{inset:2\.59%/);
});

test("keeps three saved watermark templates and the full official palette available during editing", async () => {
  const [page, api] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/api-client.ts", import.meta.url), "utf8"),
  ]);
  for (const label of ["DEFAULT_WATERMARK_TEMPLATES", "[0,1,2]", "模板 {index + 1}", "保存当前模板", "perler-watermark-templates", "默认使用模板 1", "MARD 全部色号", "MARD 官方全色号", "绘制到图纸后会加入颜色方案"]) {
    assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(page, /getBrandColors\("MARD"\)/);
  assert.match(api, /bead-brands\/\$\{brandCode\}\/colors/);
});

test("offers a mirrored full-pattern preview and sends the mirror export option", async () => {
  const [page, api] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/api-client.ts", import.meta.url), "utf8"),
  ]);
  for (const label of ["同时导出镜像完整图纸", "镜像图纸预览", "includeMirroredPattern", "mirror={mirrorPreview}"]) {
    assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.match(api, /include_mirrored_pattern/);
});
