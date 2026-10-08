# PDOS Next

按 2026-10-02 完整目标架构建设的独立新工程。范围、依赖和验收见[执行方案](../docs/design/2026-10-02-pdos-next-execution-plan.md)，活动状态仅在[唯一清单](../tasks/ai-native-integrated-todo.md#pdos-next-queue)。

`server/` 为独立 FastAPI 领域服务和迁移链，`web/` 为 Next.js 同源应用，`contracts/` 为合订本重建的来源标记目录；不导入旧业务模块或旧数据库。设计目录不代表全部操作已开放。

本地路径包含来源事实、原件上传/扫描/定位解析/下载、人工不可变产品定义和规格、排队委派/取消，以及持久工作流和能力检查点。模型默认关闭；协议网关和预算账本需服务器绑定的当前资格与出站许可，不能从前端启用或把合成资格晋升为真实资格。扫描与解析分别保留事实，解析使用有界容器；OCR、生产扫描规则维护及真实资格尚待接入。

第二波新增同产品派生/三方重核、真正项目固定定义、工程/NPI首版计划及原调用用量对账。通用一次确认绑定实际变更、固定来源和当前对象；首版计划的工作包/任务/依赖与回执在一个事务建立。预测保留工时区间、未知和实际日历规则，批准基线/承诺/实绩分别为空；后续计划修订、跨产品平台采用和正式发布仍未开放。费用对账只核对原调用，不重发模型结果未知的请求。

工程路径复用不可变Part/BOM、双配置与计划Build，接入实际配置/产出批次/样件身份，以及固定来源的供给快照、齐套、成本和验证准备。专业前段从固定准备形成独立请求版本，逐项核对方法，记录零占用的暂定窗口；人员职责、人员资格与AI资格分别核对，原始准备与计划Build不变。原件保留事实、具名可逆访问隔离和恢复独立于扫描安全，未知结果只核对原尝试。当前完整资源占用、正式放行/开工、实物交样/接收、TestRun与结果路径尚未接通；具体证据和缺口以唯一清单为准。

## 独立安装和检查

在 `server/` 执行 `uv sync`，在 `web/` 执行 `pnpm install --frozen-lockfile`。以下工具在仓库根用 `pdos-next/server/.venv/bin/python` 执行，不读取旧 `.env`，私有状态与凭据只放在忽略的 `.local/`。

- `tools/local_environment.py create`：新建或核对本任务独立 `pdos_test`，每次操作均检查实例ID、loopback端口和marker；新环境的启动证据按marker另存，不覆盖历史。
- `tools/workflow_environment.py create-db`：新建或核对独立 Temporal/visibility/checkpoint PostgreSQL 实例，checkpoint角色不共享业务凭据。
- `tools/workflow_environment.py create-server`：使用官方 Temporal auto-setup 镜像与独立 PG；镜像不可用时可以使用已核对官方来源和摘要的本地CLI，通过 `serve-native` 启动持久 SQLite **开发服务**。这条替代路径不算生产 PostgreSQL 工作流验收。
- `tools/workflow_environment.py health`、`worker`：核对命名空间、启动四并发活动与 Outbox 分发。当前本地worker只允许合成预览租户，模型为None；等待目标不自动重试模型。
- 使用与唯一清单当前候选对应的检查工具；第十波 `tools/wave10_check.py schema` 核对schema，`check <明确测试路径>` 做受影响检查，`joint` 按冻结范围并行、结构修改用例最后串行。checkpoint测试必须有单独明确URL，没有旧地址回退。`migrate`只允许首次备份和新迁移往返；往返在该版业务数据写入前执行，之后禁止下迁。必要备份不覆盖，恢复须先核对实际head和实例身份。
- `tools/local_environment.py serve-api`、`serve-web`：本地API8898/Web3028，服务器持有预览会话；先准备好独立工作流环境。API只在已核对的临时实例和精确预览范围启用本地合成专业事实，不授真实资格。
- 每轮冻结候选与实际浏览器证据均由[唯一清单](../tasks/ai-native-integrated-todo.md#pdos-next-queue)链接。`wave*_verify.py`只核对各轮固定合成演练；这些工具不是通用生产验收脚本，旧版本不应对后续已推进数据重跑。

历史G0的检查日志不再由旧check/migrate入口覆盖。恢复演练工具只操作核对过的本轮进程，使用合成材料；正常运行不反复执行演练。

正常服务必须显式配置非所有者 `DATABASE_URL` 和只读 `AUTH_DATABASE_URL`，迁移另用 `MIGRATION_DATABASE_URL`。真实部署、真实身份、OSS/S3接线、生产扫描/OCR、模型资格、出站许可和正式发布仍按对应交付及批准办理。私有原件使用服务器配置的本地目录；已登记原件和未知上传保持保护，仅满足完整引用/保留条件的显式终止上传可具名隔离。隔离只改变访问标记，物理回收未开放。

本地预览暂留。收尾先停止本轮worker、API、Web和Temporal；`tools/local_environment.py destroy`只删除marker匹配的业务测试容器，不能当作整个工作流环境已经清理。独立状态库、私有原件和必要备份应按核对过的资源逐项处理，不清理旧环境。
