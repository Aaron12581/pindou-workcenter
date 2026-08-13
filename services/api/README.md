# 阶段 0 API

当前实现本地优先的真实数据闭环：创建项目、上传 1–10 张
JPG/PNG/WebP 素材、重新读取项目、素材预览、图纸生成与编辑、版本、检查、
正式导出，以及 2–10 张正式 2D 素材的批量生成、失败重试、确认和导出。

## 本地启动

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload
```

默认使用本地 SQLite 便于开发和自动测试。设置 `.env` 中的
`PERLER_DATABASE_URL` 后使用 PostgreSQL；正式环境以
`contracts/migrations/0001_initial.sql` 为完整数据库基线。

所有数据默认保存在 `services/api/.data/`：

- `perler.db`：项目与素材元数据
- `uploads/`：原始素材
- `backups/`：生成的项目备份包

macOS 可双击 `scripts/start-local.command`，Windows 可双击
`scripts/start-local.bat`。第一次启动会安装本地依赖，之后不会重复安装。

## 测试

```bash
PERLER_DATABASE_URL=sqlite:///./.data/test.db .venv/bin/pytest -q
```
