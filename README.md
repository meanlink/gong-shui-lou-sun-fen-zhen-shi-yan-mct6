# 供水漏损分诊实验

决策树与模型选择的真实业务分析小型项目。完整模拟客户、痛点、上下游、算法公式与一天工作剧本见 [BUSINESS.md](BUSINESS.md)。

## 模块与业务流程
数据接入（JSON/CSV、字段验证、批次指纹）→ 参数化分析（异步 Python worker）→ 结果复核（指标、图形、明细、解释）→ **验真复算（封存凭据、原版规则独立复算、逐段与指标比对）** → 批准 → 定时分发（本地收件箱、CSV/JSON、SHA256）；另有业务总览和审计轨迹。
三个贯穿全栈的实体：Dataset 数据批次、Job 分析任务、Report 分发计划；辅助 User、Audit、Delivery、Verification 验真凭据。

## 验真复算（算法升级后仍可证明历史结论）
新试验完成时 worker 立即封存 **原输入快照、参数、规则版本、可独立执行的冻结规则包源码与各部分 SHA256 指纹**（`verifications` 表，凭据只封存一次，重复完成不另出凭据）。
规则版本登记在 `backend/src/rule_versions/`：当前为不可变的 `rules_v1.py`；升级算法只能新增 `rules_vN.py` 并在注册表登记，禁止改动已冻结版本。验真始终按凭据记录的版本取回原规则独立执行，不调用当前算法。
- 发起：分析员/管理员在「验真复算」页（或 `POST /verifications/job/{id}`）发起；worker 按封存原版复算，逐段分诊、指标、图表与结论逐项比较，任一差异或缺件即判 **failed**，且绝不修改原成绩。
- 闸门：只有验真 **passed** 且当前成果指纹与封存一致、封存完好，才能批准与创建/执行分发；否则接口返回 409，前端按钮置灰。
- 防篡改：封存清单带整体指纹，任何封存改动在读取时立即判失效（failed）；冻结规则源码在复算前再校验一次指纹。
- 可靠性：同一核验用 `run_key` 标识，中断后 worker 重启恢复同次核验；`worker_token` 占用令牌保证并发重试不重复执行，旧执行的迟到写回被 CAS 拒绝，不能覆盖接管结论。
- 历史试验：上线前完成、缺少封存依据的试验明确标记 **unverifiable（不可验真）**，禁止用新版规则补算冒充，也不能批准或分发。
页面可发起核验、查看进度（自动轮询）、差异原因并下载完整封存凭据 JSON。接口：`GET /verifications`、`GET /verifications/job/{id}`、`POST /verifications/job/{id}`、`GET /verifications/{id}/evidence`。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18208；后端文档 http://localhost:19208/docs；数据库宿主端口 17708。
`SEED_DEMO=true` 自动幂等 seed；不覆盖用户修改。手动 seed 命令可重复执行。

## 演示账号与权限
|账号|密码|真实权限|
|---|---|---|
|admin@demo.local|Demo123!|接入、执行、批准、分发、暂停、读取与下载|
|analyst@demo.local|Demo123!|接入、执行、读取与下载；不能批准或安排分发|
|viewer@demo.local|Demo123!|只读与下载|

## 技术与本地开发
Python 3.12 / FastAPI / SQLAlchemy / NumPy / SciPy / scikit-learn；PostgreSQL 16；Redis 7；Nginx；原生 HTML CSS JavaScript ES modules（用户指定）。后端所有校验、持久化和算法在服务端。无前端打包步骤。
后端：安装 backend/requirements.txt，设置 DATABASE_URL、REDIS_URL、JWT_SECRET、ARTIFACT_DIR 后在 backend/ 执行 `python -m migrations.initial`、`python -m scripts.seed_demo`、`uvicorn src.main:app`，另开 `python -m src.worker`。前端使用带 /api 反向代理的 Nginx，直接打开 index.html 不支持 API。

## 目录与工程约定
backend/src/{models,schemas,services,routes,controllers,middlewares,constants,config,utils,rule_versions}；backend/scripts/seed_demo.py；backend/migrations/initial.py。
frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}。
Role 枚举：admin/analyst/viewer；JobStatus：queued/running/completed/failed；VerificationStatus：pending/running/passed/failed/unverifiable。后端 backend/src/constants/enums.py，前端 frontend/src/constants/enums.js；路由权限在 middlewares/auth.py；页面按相同角色控制操作入口。

## 环境变量与 Docker
COMPOSE_PROJECT_NAME=water-triage；FRONTEND_PORT=18208；BACKEND_PORT=19208；DB_PORT=17708；DB_PASSWORD、JWT_SECRET 见 .env.example；SEED_DEMO 默认 true。共享命名产物卷供后端下载与 worker 写入，数据库/Redis 各持久卷。
恰好五服务均有健康检查。Redis 队列加 SQL 排队状态兜底；worker 按 next_run 生成本地收件箱文件。周期 60 秒至 30 天。分发结果为批准分析的固定快照；若需新数据重新计算并建立新计划。当前不连接邮件或企业聊天。
错误响应、请求编号、Redis 每 IP 每分钟 240 次限流、JWT 和数据库操作审计。演示密钥与密码仅供本机模拟；生产部署前配置独立密钥与账号。

## 数据与验收
所有数据为固定随机种子生成的模拟业务数据，不能作为实际生产决策证据。项目独立算法、输入边界及业务局限详见 BUSINESS.md。测试与截图统一存放 ../../test-artifacts/gb-1009/，源码不含日志/截图/测试报告；验真复算功能测试（29 个用例）的仓库内镜像位于 gitignored 的 .local-test-artifacts/，便于无 Docker 环境用 SQLite 复跑。
清理本项目演示数据：`docker compose down -v --remove-orphans`（会删除本项目命名卷）。

## License
MIT，见 LICENSE。
