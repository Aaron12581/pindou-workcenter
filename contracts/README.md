# 拼豆图纸转化工具：阶段 0 工程合约包

版本：`1.0.0`  
基线日期：`2026-07-28`

本目录把《阶段 0：数据模型与技术工程设计 v1.0》落实为可执行、可校验的工程协议。

## 内容

- `migrations/0001_initial.sql`：PostgreSQL 16 首次迁移，包含 11 张核心表、枚举、约束、索引和更新时间触发器。
- `openapi/openapi.yaml`：MVP API v1 的 OpenAPI 3.1 合约。
- `schemas/pattern-v1.schema.json`：图纸不可变快照 JSON Schema。
- `examples/pattern-v1.example.json`：可通过 Schema 校验的四联板示例。
- `scripts/validate_contracts.py`：离线校验 OpenAPI、JSON Schema 与示例的一致性。

## 冻结约束

- 单用户私有使用，但所有业务数据仍保留 `owner_id` 边界。
- 单批次支持 1–10 张 JPG、PNG 或 WebP。
- 图板只支持标准 `29 × 29` 针正方板及 5 mm 拼豆。
- 图板布局只支持单板、双联横板、双联竖板、四联方板、六联横板。
- 原图必须先确认正式 2D 候选，再生成少色、标准、丰富三种图纸候选。
- 首发色库为 MARD `official-v1`，色库只读。
- 图纸 JSON 是事实源；PDF、PNG 均由不可变图纸版本重新渲染。

## 本地校验

```bash
python scripts/validate_contracts.py
```

若本机安装了 PostgreSQL，可额外在空数据库执行：

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/0001_initial.sql
```

## 后续工程接入

1. 后端从 OpenAPI 生成类型或路由骨架。
2. 数据库迁移交由 Alembic 管理，但 SQL 中的约束语义必须保留。
3. 保存图纸版本前，先按 `pattern-v1.schema.json` 校验，再由服务端重算统计值和校验和。
4. API 错误统一返回 `ErrorResponse`，异步任务统一通过 `Job` 查询。

