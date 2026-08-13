# 拼豆图纸工作台 · 本地优先版 v0.20.49

## v0.20.49：Mac 稳定启动版

本版直接运行已经构建好的正式前端，不会在启动时下载 npm 组件，也不会调用 Vite/Rollup 开发组件。解压后双击 `scripts/start-local.command` 即可启动。

- 安装包内含离线前端组件缓存；首次启动会优先从本地安装，不再依赖 npm 网络下载。
- 请保留项目根目录的 `.npm-offline-cache` 文件夹。
- 若此前启动失败留下了不完整的 `node_modules`，仅删除项目根目录的 `node_modules` 后重新双击启动；不会影响 `services/api/.data` 内的项目数据。

## v0.20.47：本地启动稳定性修复

- 首次启动下载前端组件时，网络波动会自动重试 3 次。
- 只有前端组件准备完成后才启动后端，失败时不会留下半启动服务。
- 失败提示改为可操作的中文说明：恢复网络后直接再次双击启动文件即可。

## v0.20.46：编辑器批量擦除

- 编辑工具新增“批量擦除”：拖拽框选一个区域，松开后会一次性清空该区域内的全部豆点。
- 批量擦除作为一次编辑记录，可使用“撤销”完整恢复；颜色方案、数量、预览和导出会按最新图纸自动同步。

## v0.20.31：本地图纸主体轮廓保护

- 本地图纸引擎在缩放前单独提取连续、深色的源图轮廓证据，避免头发、发髻、衣物外沿等粗线条被相邻填充色平均稀释。
- 轮廓证据会优先参与色号映射，并跳过后续的近似色合并；面部和服饰内部的低对比细阴影仍按既有规则收束。
- 只保留源图中实际存在的结构，不会补画新的轮廓、五官或纹理。

## v0.20.30：52×52 单板与自定义图板继承

- 标准单板统一修正为 52×52 针；默认拼板、分板线、导出、2D 设计提示与图纸生成均按新尺寸计算。
- 图纸阶段会继承图板规划中确认的自定义组合，并明确显示其实际针数；例如 3×2 板将按 156×104 针生成与分板。
- 图纸页仍可查看默认规格，但自定义规格不会被静默替换为默认四联板。

## v0.20.27：本地图纸背景与细节忠实度修复

- 本地引擎在落格前会清除边缘连通、明显为白色/浅色的背景画布；背景不再占用豆位或色号预算。
- 面部与连续同色区域改为严格以正式 2D 为依据；不再自动补画眼睛、眉毛、嘴部或额外阴影色块。
- 已在生成统计中记录本次是否执行背景清除及清除像素数，便于图纸检查。

## v0.20.26：多素材独立链路与项目归档

- 图板、图纸与导出均绑定当前选定的正式 2D，不再默认使用项目第一张素材。
- 左侧项目库改为真实本机项目入口；“已归档”可查看并恢复项目。
- 项目和素材支持右键软归档；素材归档不会删除图片、2D、图纸或版本记录。

## v0.20.24：直接导入正式 2D

- 在「2D」阶段新增“直接导入 2D”，可跳过原图上传与 2D 重绘，直接进入图板和图纸流程。

## v0.20.23：2D 生成按钮状态修复

- 生成按钮不再因首次模型状态读取失败而静默禁用。
- 点击生成时会重新读取模型状态，并显示连接或配置错误。

## v0.20.22：按实际拼豆色数调整三档上限

- 少色、标准、丰富的色数上限分别调整为 16、30、42 色；这三项都是上限，系统不会为了凑满额度而添加无意义的过渡色、阴影或高光色。
- 同一套上限同时用于 2D 设计稿收束、图纸大模型提示和最终图纸落格，避免上下游色数预算不一致。

## v0.20.21：按拼豆制作规则收束 2D 与图纸细节

- 2D 的简化、标准、丰富改为三套拼豆设计稿规则：优先剪影、身份特征和大色块；不再把衣料褶皱、甲片纹样、碎高光和连续渐变当作需要还原的细节。
- 图纸大模型会按实际图板尺寸和方案获得明确的细节预算：少色最多 16 色、标准最多 30 色、丰富最多 42 色；这是上限而非固定色数。
- 大模型图纸落格后会合并超出方案预算的近似阴影/高光色，并仅移除被同色完全包围的单格杂点，保留轮廓、面部和细长配件的结构。
- 图纸请求会读取已确认 2D 的简化档位，禁止模型在图纸阶段重新补回 2D 有意删除的插画细节。

## v0.20.20：图纸直出传输规范化与定位诊断

- 图纸大模型请求会先将确认的透明 2D 展平为 1024×1024 的 RGB PNG，使用统一背景并限制输入形态，避免透明通道与不受控载荷造成的连接中断。
- 失败信息增加输入尺寸、传输字节数、透明像素占比、自动重试上限，以及未收到 HTTP 响应/TLS/DNS 的断开阶段。
- 若进程继承代理设置，只显示代理主机与端口，不显示账号、密码或 API Key。

## v0.20.19：2D 主体边缘检查修正

- 主体边缘检测只统计 alpha ≥ 64 的有效主体像素，忽略模型去背留下的极淡透明边缘，不再把四周留白充足的成图误报为贴边。
- 候选检查直接显示有效主体的左、上、右、下留白像素与安全边距；真实构图过紧会给出提醒及具体数值。
- “主体进入安全边距”改为可继续确认的提示，确认时不会因为该提示失败，也不会暗中重写已生成的 2D 成图；图板阶段可继续调整位置与留白。

## v0.20.18：OpenAI 参考图保真与请求诊断

- 默认 2D 模型参考图改为完整原图，不再对深色复杂画面自动去背；仅在用户手动框选或裁切时才按选区保留原始像素，防止斗笠、甲胄、佩剑等身份特征被预处理误删。
- 2D 提示词将参考图设为视觉依据，明确禁止以泛化角色替换人物的脸部、服装、色块、武器、动作和身份特征。
- OpenAI 的 2D 与图纸调用改为进程内复用同一个客户端，避免两个相邻请求重复建立 DNS/TLS/代理连接。
- 调用失败会在页面和终端显示诊断编号、请求耗时、异常因果链以及 OpenAI 错误码 / Request ID（如有），便于准确区分连接层失败、超时和服务端错误。
- 延续版本 UI 基线闸门：若旧版侧栏/大卡片版本记录再次出现，构建会失败，不能打包。

v0.12.2 新增阿里云百炼中国站（北京）图像生成供应商。默认使用
`qwen-image-2.0` 进行参考图重绘，也可将模型改为账户中已开通的
`qwen-image-2.0-pro` 或其他兼容图像编辑模型。OpenAI 仍可切换使用。
密钥与 Workspace ID 只从本机 `.env` 读取。

百炼北京站配置：

```bash
PERLER_IMAGE_PROVIDER=dashscope
DASHSCOPE_API_KEY=你的百炼API-Key
DASHSCOPE_WORKSPACE_ID=你的业务空间ID
PERLER_IMAGE_MODEL=qwen-image-2.0
```

OpenAI 配置：

```bash
PERLER_IMAGE_PROVIDER=openai
OPENAI_API_KEY=你的密钥
PERLER_IMAGE_MODEL=gpt-image-2
```

v0.12.0 新增真实成品 2D 图像模型链路，默认使用 OpenAI `gpt-image-2` 图像编辑能力。
v0.12.1 新增候选数量选择：可仅生成简化、标准或丰富中的一张，也可一次生成三张。
API 密钥只从本机环境变量读取，不写入数据库、项目备份、日志或浏览器。
OpenAI 模式在 `services/api/.env` 使用：

```bash
OPENAI_API_KEY=你的密钥
```

模型调用会产生 API 费用；单张模式调用一次，三张模式调用三次。未配置密钥、鉴权失败、限流或
超时均不会覆盖原图和已经确认的正式 2D。

v0.11.1 修复复杂竖图可能被错误主体蒙版裁成横向窄带的问题。可疑主体范围会
自动回退为完整原图并保持纵横比例，同时新增主体几何完整性检查。当前离线
色彩/轮廓处理已明确标记为“2D 预处理参考稿”，不再冒充重新绘制的成品 2D，
也不能确认为正式资产。启动脚本会明确检查 Python 3.10+。

v0.11.0 新增复杂图片预处理：可用保留/移除画笔修正主体蒙版，框选多个主体，
调整横纵裁切和全身/半身/大头构图，并查看背景复杂度、主体触边、透明覆盖率与
识别质量分数。预处理改变后，旧正式 2D 会失效，下游图纸明确标记为过期。

v0.10.0 新增“原图 → 2D 预处理”基础链路：本地背景估计与主体提取、简化/标准/丰富
三档参考稿与原图对照。v0.11.1 已纠正此前将参考稿描述为成品 2D 的错误。v0.9.0 的
2–10 张批量生产、正式 2D 素材门槛、任务队列、逐项独立生成、
部分失败不中断、按原始参数快照重试、批量确认与批量 ZIP 导出。项目备份与恢复
会保留批次、任务状态、重试次数、确认状态和参数快照。

v0.8.0 新增正式导出闭环：基于已保存修订生成带色号总图 PNG、29×29 分板 PNG、
MARD 色号用量 CSV、完整 Pattern JSON、多页可打印 PDF，以及带 SHA-256 校验值的
manifest，并统一下载为 ZIP 图纸包。

v0.7.0 在 v0.6.0 真实网格编辑上新增手动版本快照、版本只读对比与恢复，并提供
孤立豆、相近色、轮廓对比和分板线关键区域检查。历史恢复会生成新的工作副本修订，
不会覆盖或删除已有快照。

v0.6.0 在真实网格编辑上新增框选、移动、复制、缩放与平移，并支持色号、坐标、
标准标线和分板线的显示开关。编辑页继续直接读取 Pattern JSON，支持画笔、橡皮、
吸色、区域填充、撤销/重做和防抖自动保存。保存使用修订号
检查，旧页面不会静默覆盖较新的图纸内容。

## 工程基础

A clean full-stack starter running on
[vinext](https://github.com/cloudflare/vinext), with optional Cloudflare D1 and
Drizzle support.

## Prerequisites

- Node.js `>=22.13.0`
- Python `>=3.10`（推荐 3.12）
- Linux with `flock`, `curl`, and GNU `timeout`

## Sites Lifecycle

The Sites lifecycle CLI runs the locked dependency install before returning this checkout. Edit the source under `app/`, then checkpoint when a coherent milestone is ready to inspect or share. The remote Sites builder runs `npm run build` against the pushed commit. Do not repeat install or build as a normal pre-checkpoint step.

This starter does not use `wrangler.jsonc`.

`install:ci` is intentionally a single, non-retrying `npm ci`. It refuses a concurrent install for the same project, consumes a matching image-seeded npm cache with `--prefer-offline` while retaining registry fallback for a missing cache object, otherwise downloads and verifies the complete vinext tarball recorded in `package-lock.json`, limits npm to one socket, and terminates a stalled install. `build` applies a short timeout and then validates the Sites artifact. These helpers target Linux and use GNU `timeout`; they are not native macOS scripts.

Scripts that need writable project-scoped home, npm, XDG, and temporary paths use `scripts/sites-env.sh`. The `dev` and `start` scripts honor the caller's runtime environment and keep Wrangler logs inside the checkout. The generated `.sites-runtime/` directory is disposable and ignored by Git.

## Included Shape

- edit site code under `app/`
- `app/chatgpt-auth.ts` provides optional dispatch-owned ChatGPT sign-in helpers
- `.openai/hosting.json` declares optional Sites D1 and R2 bindings
- `vite.config.ts` simulates declared bindings for local development
- `db/index.ts` reads the D1 binding from the Cloudflare Worker environment
- `db/schema.ts` starts intentionally empty
- `examples/d1/` contains an optional D1 example surface
- `drizzle.config.ts` supports local migration generation when needed

## Workspace Auth Headers

OpenAI workspace sites can read the current user's email from
`oai-authenticated-user-email`.

SIWC-authenticated workspace sites may also receive
`oai-authenticated-user-full-name` when the user's SIWC profile has a non-empty
`name` claim. The full-name value is percent-encoded UTF-8 and is accompanied by
`oai-authenticated-user-full-name-encoding: percent-encoded-utf-8`.

Treat the full name as optional and fall back to email when it is absent:

```tsx
import { headers } from "next/headers";

export default async function Home() {
  const requestHeaders = await headers();
  const email = requestHeaders.get("oai-authenticated-user-email");
  const encodedFullName = requestHeaders.get("oai-authenticated-user-full-name");
  const fullName =
    encodedFullName &&
    requestHeaders.get("oai-authenticated-user-full-name-encoding") ===
      "percent-encoded-utf-8"
      ? decodeURIComponent(encodedFullName)
      : null;

  const displayName = fullName ?? email;
  // ...
}
```

## Optional Dispatch-Owned ChatGPT Sign-In

Import the ready-to-use helpers from `app/chatgpt-auth.ts` when the site needs
optional or required ChatGPT sign-in:

- Use `getChatGPTUser()` for optional signed-in UI.
- Use `requireChatGPTUser(returnTo)` for server-rendered pages that should send
  anonymous visitors through Sign in with ChatGPT.
- Use `chatGPTSignInPath(returnTo)` and `chatGPTSignOutPath(returnTo)` for
  browser links or actions.
- Pass a same-origin relative `returnTo` path for the destination after sign-in
  or sign-out. The helper validates and safely encodes it.
- Mark protected pages with `export const dynamic = "force-dynamic"` because
  they depend on per-request identity headers.

Dispatch owns `/signin-with-chatgpt`, `/signout-with-chatgpt`, `/callback`, the
OAuth cookies, and identity header injection. Do not implement app routes for
those reserved paths. Routes that do not import and call the helper remain
anonymous-compatible.

SIWC establishes identity only; it does not prove workspace membership. Use the
Sites hosting platform's access policy controls for workspace-wide restrictions,
or enforce explicit server-side membership or allowlist checks.

Use SIWC for account pages, user-specific dashboards, saved records, and write
actions tied to the current ChatGPT user. Leave public content anonymous.

## Diagnostic Commands

- `npm run install:ci`: perform the one bounded lockfile install
- `npm run dev`: start the Vite/Vinext development server
- `npm run build`: build and validate the deployable Sites artifact
- `npm run start`: start the built Vinext application
- `npm test`: build, validate, and verify the rendered development-preview metadata
- `npm run validate:artifact`: recheck an existing artifact's manifest and ESM `default.fetch` export
- `npm run db:generate`: generate Drizzle migrations after schema changes

Use build and validation commands for targeted diagnosis after a remote failure, not as part of the normal checkpoint path.

The timeout defaults can be overridden for a controlled canary with `SITES_INSTALL_TIMEOUT`, `SITES_INSTALL_KILL_AFTER`, `SITES_BUILD_TIMEOUT`, and `SITES_BUILD_KILL_AFTER`. A timeout fails the command; the helpers never retry an unchanged install or build.

## Learn More

- [vinext Documentation](https://github.com/cloudflare/vinext)
- [Drizzle D1 Guide](https://orm.drizzle.team/docs/get-started/d1-new)
# 拼豆图纸工作台 v0.20.6

## v0.20.6：显式选择生成路径，本地先简化再落格

- 图纸候选页在生成前提供“本地引擎”与“大模型直出”两种互斥选择，结果记录实际生成路径，不再自动回退或混淆来源。
- 本地引擎改为语义简化优先：中间画布进行相邻近色合并与纹理噪点清理，随后保护面部、轮廓、佩剑等细长关键结构，最后映射真实 MARD 色号与图板网格。

## v0.20.5：改为“模型成图 → 确定性落格”，彻底移除文本网格调用

- 不再让视觉模型输出 JSON、坐标行程或定长字符网格；这些协议在真实调用中均已证明不可靠。
- 图纸模型直接根据正式 2D 生成一张无网格的像素成图；后端仅以最近邻取样将这张图机械转换为可编辑格子，并映射到 MARD 官方色号。
- 不使用本地初稿、语义修补、面部补画、降噪或本地重新设计；图案内容只由模型返回的图像决定。
- 已配置模型若生成失败，接口返回 502 和真实错误码，绝不再悄悄生成并保存一张本地回退图纸。

百炼请继续使用已验证可生成正式 2D 的图像模型配置，例如：

```bash
PERLER_IMAGE_PROVIDER=dashscope
PERLER_IMAGE_MODEL=qwen-image-2.0
PERLER_PATTERN_AI_MODE=auto
```

## v0.20.4：改用视觉模型更稳定的行文本图纸协议

- 不再要求视觉模型生成严格 JSON；每块图板以“调色板 + 定长字符行网格”直接返回。
- 即使服务商附带标题或代码围栏，服务端也会严格提取图纸内容并校验，不会自行补画任何格子。
- 仍只参考正式 2D，仍不传递或使用本地初稿；JSON 返回仍兼容，以便已完成的请求正常落盘。

## v0.20.3：修复模型 JSON 包装导致的误判失败

- 兼容百炼等 OpenAI 兼容视觉接口可能返回的 Markdown 代码围栏、UTF-8 BOM 与简短前缀文字；服务端会从中提取完整 JSON 对象后再验证。
- 图纸网格仍严格校验每行长度、符号、MARD 官方色号与图板范围；截断或真正格式错误的内容不会被放行。
- 失败提示明确说明“模型已返回内容但无法提取完整图纸 JSON”，可直接重试。

## v0.20.2：修复分板模型生成超时

- 每块 58×58 图板改用“符号调色板 + 定长行网格”的紧凑结构化协议，不再返回大量坐标行程 JSON；正常输出量显著降低。
- 单块模型等待上限由 90 秒提高至 180 秒，适配细节丰富的正式 2D。
- 解析后仍严格校验 MARD 官方色号、每行长度和分板边界，再转换为原有可编辑图纸数据。
- 规划器版本已升级，旧的长坐标输出缓存不会复用。

## v0.20.1：修复大尺寸图纸模型调用失败

- 116×116 及更大图纸改为按 58×58 标准板直接向视觉模型生成，再合并为完整可编辑图纸；不再要求单次输出超长 JSON 网格。
- 百炼 Qwen3-VL 的结构化输出显式关闭思考模式，避免 JSON Mode 与思考模式冲突。
- 调用失败时保存稳定错误码与可读原因，候选页会明确显示，不再只显示“调用失败”。

## v0.20.0：大模型直接生成受约束图纸网格

- 图纸阶段只把正式 2D 与图板、配色要求发给视觉模型；不再生成或传入本地初稿。
- 模型以压缩行程网格直接输出 MARD 官方色号；服务端只校验坐标/色号、补全分板信息并保存原有可编辑数据。
- 缓存按正式 2D、图板与颜色方案隔离；旧版语义规划不会被复用。
- 只有模型未配置、调用失败或输出无效时才回退本地图纸，并在界面明确提示。

## v0.19.1：修复语义规划“显示应用但网格未改变”

- 模型标注的五官关键点和细长配件路径现在会形成受约束的真实针位调整。
- “已应用”改为以最终图纸相对本地初稿的网格差异为准。
- 右侧显示实际调整针数；零变化时明确提示规划未改变网格。
- 图纸引擎升级为 `semantic-hybrid-v7`。

## v0.19.0：大模型语义规划进入图纸生成

- 图纸生成先产出确定性初稿，再用视觉模型对照正式 2D 与初稿。
- 一次结构化视觉调用规划脸部、五官、服饰、武器和细长配件保护区。
- 本地引擎根据规划重新落格，仍保证精确网格、MARD 官方色号和可编辑性。
- 同一正式 2D 与同一图板尺寸复用语义规划，切换颜色方案不重复消耗额度。
- 视觉模型不可用或调用失败时安全回退本地图纸，并在界面明确显示。
- 图纸 JSON 保存规划版本、模型、重点保留项、评估与回退状态。
- 图纸引擎升级为 `semantic-hybrid-v6`。

百炼继续复用现有 Key 和 Workspace ID，新增可选配置：

```bash
PERLER_VISION_MODEL=qwen3-vl-flash
PERLER_PATTERN_AI_MODE=auto
```

设置 `PERLER_PATTERN_AI_MODE=off` 可关闭图纸阶段的大模型调用。

## v0.18.0：工作区与版本、图纸、导出一致性

- 01–04 阶段左侧栏默认收起并记忆状态。
- 素材页支持四边拖动裁切，裁切参数进入 2D 模型输入。
- 2D 仅展示最新生成批次，保留并可导出历史模型资产。
- 图板铺满模式使用约 3 针安全边距。
- 图纸阶段恢复项目最后一次结果，不再切页重生成。
- 图纸与编辑统一使用方格填色加色号。
- 图纸配色不再使用 12/24/40 的硬性颜色上限。
- 导出预览与真实分板边界共用同一网格数据，完整图例为色号-数量。

## v0.17.0：复杂度路由与分档 2D

- 本地素材复杂度分析与图板/2D方案推荐。
- 简化、标准、丰富使用不同的图板适配重绘策略。
- 图纸引擎升级为 `adaptive-quality-v5`。
- 质量评分改为结构、颜色误差与可制作性实算。
- 百炼内容安全拒绝使用独立错误提示。
- 启动脚本、界面、后端与安装包版本统一。

## v0.16.0：细节稳定引擎（P1.1）

- 在固定 116×116 分析尺度上确定真实色板，使同一正式 2D 的 2×2、3×3 等联板共享身份色，避免扩大图板后服饰主色退化。
- 对有足够针数的已识别人脸执行保守的符号化五官重建，分离双眉、双眼与嘴部。
- 图纸 JSON 写入 `engineVersion: detail-stable-v4`，并记录跨尺寸稳定策略。
- 保持旧项目、旧图纸、正式 2D 与 `.data` 兼容；重新生成图纸不调用图片模型。

## v0.15.0：语义区域细节引擎（P1）

- 在透明正式 2D 上确定性识别人脸候选区、五官深色细节、细长武器/饰物、主体轮廓与服饰区。
- 面部、五官、武器、轮廓和服饰分别获得颜色预算，小面积关键细节不再只与大面积服饰按像素数量竞争。
- 面部和武器区域跳过普通孤立点清理，避免眼睛、嘴部与一针宽武器结构被误删。
- 肤色识别增加色序和色差约束，避免红色服饰被误判为面部。
- 图纸 JSON 写入 `engineVersion: semantic-region-v3`，并记录只读的区域策略与区域数量诊断。
- 旧图纸、正式 2D 与项目数据结构保持兼容；只有重新生成图纸时使用 P1 引擎。
- 本版本仍为本地确定性算法，不调用图片模型。

## v0.14.0：第二代区域感知图纸引擎（P0）

- 图纸颜色直接匹配真实 MARD 色库，不再经过 FASTOCTREE 中间减色。
- 色差算法升级为经过标准参考数据校验的 CIEDE2000。
- 移除“原图全局主色影响每个格子”的偏色来源；原图仍保留为项目对照资产。
- 轮廓与窄结构在缩小时获得更高权重，并对剑、发簪等结构执行受限覆盖保护。
- 色板预算按边缘与高饱和辨识色加权分配，面部边缘、服饰主色和武器不再只按面积竞争。
- 色号落格后清理非边缘区域的孤立噪点，保留受保护轮廓。
- 图纸 JSON 写入 `engineVersion: region-aware-v2`，旧图纸仍按原数据打开和导出。
- 本版本生成图纸只运行本地确定性算法，不调用图片模型。

## v0.13.0：58×58 标准板与全项目真实数据流

- 标准单板由 29×29 更新为 58×58，新图纸按其进行多板组合。
- 图纸生成改用感知色彩距离，并保留细剑、配件等窄结构。
- 原图/2D 对比、图板预览、侧栏与素材归属全部读取当前项目。
- 素材按原始宽高比预览，“适应/裁切”具有真实显示状态。
- 自定义图板组合可设置横向、纵向板数并用于真实图纸生成。
- 旧 29×29 项目继续按其自身图板元数据编辑和导出。

## v0.12.8：正式 2D 到真实图纸的资产关联修复

- 图纸生成只提交当前项目的 `confirmed_2d` 资产，不再误取第一张原始素材。
- 兼容 v0.12.7 已有项目：旧页面若提交原图 ID，后端会解析其唯一关联的正式 2D。
- 图板页选择的单板、双联、四联或六联布局会带入图纸生成页。
- 不调用图像模型，不需要重新生成已经确认的 2D。

## v0.12.7：正式 2D 确认按钮前置拦截修复

- 百炼模型候选即使因纸纹背景暂时标记为“需检查”，也允许进入本地确认接口。
- 点击“确认正式 2D”后先在本地清理背景，再执行正式质量检查。
- 离线预处理参考稿仍然禁止确认为正式 2D。
- 确认期间显示“正在本地确认…”，不会重新生成图片或消耗模型额度。
- 确认成功后保存正式资产、刷新项目并直接进入图板规划。

## v0.12.6：百炼纸纹背景兼容与真实确认修复

- 确认已有百炼候选时，本地清理边缘相连的浅色纸纹背景，不重新调用模型。
- 修复“生成后按钮可点，但后端因纸纹触边拒绝确认”的状态不一致。
- 正式确认后保存资产、更新项目阶段并进入图板规划。
- 确认失败显示具体错误码；不会静默停留，也不会消耗图片生成额度。

## v0.12.5：正式 2D 确认与图板跳转修复

- 点击“确认正式 2D”成功后直接进入“图板规划”
- 项目阶段同步更新为 `board`
- 切换正式 2D 时，旧正式 2D 对应的下游图纸会标记为失效
- 确认门槛失败时显示明确原因

## v0.12.4：百炼真实生成链路修复

- 接受百炼官方 `ws_...` 格式的 Workspace ID。
- macOS HTTPS 请求使用随应用依赖安装的可信证书链。
- 百炼提交失败与候选图下载失败均保留具体原因。
- 前端明确显示连接、证书、超时或无有效返回等失败信息。
- 失败不删除原图，也不会覆盖已经确认的正式 2D。

## v0.12.3：2D 候选生成修复

- 生成区直接选择 `1 张`或`3 张`；单张可选简化、标准、丰富。
- 标题显示当前版本，避免误开旧端口中的历史页面。
- 百炼参考图会保持比例并自动压缩到接口要求范围。
- 生成失败会显示百炼错误码、原因和 Request ID，便于准确排查。
- 启动时若 3000 或 8000 端口被旧进程占用会明确阻断，不再自动打开旧版本。

第 10 版冻结前端原型与 MVP 本地优先工程基线。

## 工程结构

- `app/`：React + TypeScript 工作台，保持冻结界面基线
- `lib/api-client.ts`：前端与 API 的类型化连接层
- `services/api/`：FastAPI 项目与素材服务
- `contracts/`：OpenAPI、PostgreSQL 迁移与图纸 JSON Schema
- `docker-compose.yml`：PostgreSQL 16 与 API 本地环境
- `scripts/start-local.*`：macOS/Linux/Windows 本地启动入口

## 首个真实闭环

1. 创建项目
2. 上传 1–10 张 JPG、PNG 或 WebP
3. 持久化素材元数据与原始文件
4. 按所有者边界重新读取项目
5. 导出 `.perler.zip` 项目备份包
6. 从备份包恢复为独立项目

## 无服务器本地使用

本地版默认使用 SQLite，不需要 Docker、PostgreSQL 或云服务器。项目数据、
素材与备份都位于 `services/api/.data/`，可整体复制到其他电脑。

- macOS：双击 `scripts/start-local.command`
- Windows：双击 `scripts/start-local.bat`
- Linux：运行 `./scripts/start-local.sh`

启动入口会同时启动本地界面和 SQLite 数据服务，并自动打开
`http://127.0.0.1:3000`。API 文档位于 `http://127.0.0.1:8000/docs`。
设置 `PERLER_DATABASE_URL` 后仍可切换 PostgreSQL，数据协议保持兼容。

本地界面已接入以下真实操作：

- 新建项目
- 上传并预览 1–10 张素材
- 从项目中心重新打开
- 下载 `.perler.zip` 项目备份
- 从 `.perler.zip` 恢复为独立项目
- 读取最近生成的真实 Pattern JSON
- 逐格绘制、擦除与吸色（右键也可吸色）
- 对同色连通区域填充
- 最多 80 步撤销/重做
- 编辑后 900 ms 自动保存并更新豆数、颜色用量

```bash
docker compose up --build
```

API 文档启动后位于 `http://localhost:8000/docs`。

## 验证

```bash
npm run lint
npm test
cd services/api
PERLER_DATABASE_URL=sqlite:///./.data/test.db .venv/bin/pytest -q
```
