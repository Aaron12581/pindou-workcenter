# macOS DMG 构建说明

此目录将 v0.20.52 封装为 Apple Silicon Mac 的 `拼豆图纸工作台.app` 与 DMG。

## 用户运行结果

- 双击“拼豆图纸工作台.app”即可打开窗口，不显示终端，也不调用 npm、Vite、Rollup 或浏览器。
- 前端、Python/FastAPI 与图纸处理依赖均随 App 内置。
- 项目数据保存在 `~/Library/Application Support/拼豆图纸工作台/data/`，升级 App 不会覆盖它。
- 首次启动可选择旧项目的 `services/api/.data` 文件夹导入；若同级有 `.env`，会仅在用户本机复制到 App 的私有设置目录。

## 构建

在一台 Apple Silicon Mac 上执行：

```bash
cd perler_desktop_v02052
chmod +x desktop/build-macos-arm64.sh
desktop/build-macos-arm64.sh
```

DMG 输出在 `desktop/dist/`。首次交付可不签名；正式对外分发前，再以 Apple Developer Program 的 Developer ID 完成签名与公证。
