# 验证独立包首版交付 · 2026-10-02

已交付可调用的请求/方法准备、真实交接范围、部分接收/退缺项、TestRun 与分批/最终结果规则和处理器，以及三组独立办理组件。主线接入条件、持久模型需求、事务病例和 DTO 映射见 [integration.md](integration.md)。本包业务接口仍待接入；没有产生真实样件、接收、开测或正式结论事实。

固定候选：`44588c11212888059b0a4061e36046dcbe5aad536ed6c9ef5dd4d335955062a9`，25 份包内源码/合成测试/局部检查配置，逐文件摘要见 [candidate.json](candidate.json)。最终检查的源码与此候选匹配；原始输出见 [checks.json](checks.json)。

| 检查 | 最终结果 | 范围 |
|---|---|---|
| 后端纯规则/合成端口处理器 | **156 passed** | 请求与原时区、前置方法/暂定时段、逐项资料、精确部分范围/数量/模穴、补齐未接收资料、身份/资格/来源/配置漂移、原值与来源核对、T1/T2拒绝、稳定意图、双对象CAS消费、破坏性冲突、逐范围时间、部分结果来源撤回、空增量最终收尾、未完成原因/责任保存 |
| 后端包内 Ruff | **通过** | 独占 domain/schemas/tests |
| 前端局部 TypeScript | **通过** | 仅verification及其实际导入；noEmit、incremental=false，无typegen/共享.next写入 |
| 前端局部 ESLint | **通过** | verification组件/guard/合成检查 |
| 前端 guard + 实际组件静态渲染 | **23 passed** | 19项纯行为守卫、4项SSR；精确pairs/部分累计接收、资料和实物分开、缺port失能、真实时间/具名开始、原值/缺项、预览范围/过期/漂移、Run状态与局部判定分开 |
| 静态边界检查 | **通过** | 零自行commit、零SQL/DB客户端/旧app直接依赖；见 [module-boundaries.json](module-boundaries.json) |

这些是合成模块检查，不能相加成业务联合验收，也不证明真实资格、数据库锁/回滚、生产资源可用或人工 Exit。

交付入口：

- 后端 `pdos-next/server/pdos_next/domain/verification/handlers.py`：`VerificationHandler.preview/execute`，12 个包内拟接入动作；`rules.py` 的资料/数量/模穴缺项及确定性判据独立可用。
- 后端 `schemas/verification/contracts.py` 与 `domain/verification/ports.py`：封闭且不可变 DTO，固定 Build 双配置/真实 SampleRef/实际配置、当前服务器 Authority、共同事务、来源原值核对和样件/资源安全消费端口。[payload-schemas.json](payload-schemas.json) 给出专用输入 schema、职责和级别，未自动注册为公共工具。
- 前端 `components/verification/index.ts`：`VerificationRequestReading`、`VerificationHandoff`、`VerificationTestRuns`。typed props/callback接主线；没有fixture注入业务页、独立网络写入口或T2代签。

关键行为：

- 主线仅计划的 Build 可先准备请求/方法/暂定时段，不能发起真实样件交接、接收或开测。缺适配端口明确返回 `INTEGRATION_REQUIRED`；实物还须样件版本、当前可用性、方法适用性与物理来源逐次复查。
- 部分接收仅确认所选 sample/item pairs；原因/下一责任人及资料缺项保留。再次接收只处理剩余范围，时间按各范围实际事实核对。未接收项可补资料；已接收方法/适用资料不能重写。
- Measurement 保留原值、单位、真实工况/设备/环境、方法、出处、观测UTC及原时区/缺项。来源存在不等于数值属实，`verify_measurement` 不接通就不能导入。未知、非数值、单位/方法/工况或设备不符不能判通过。
- 局部 Run final pass 只对固定范围成立，原请求未齐数量/模穴与实际接收覆盖时仍不设最终返回。专业结论/处置与确定性结果分开，AI不能代具名T2。
- 全部原值已经分批返回后，可空增量确认真实最终结束；未完范围与原因/下一责任人另存 `partial_returns`，不覆盖先前原值，不偷偷分派Task或权限。

消费复核：Build模型/schema、共同错误类型、UI Button/主题与所读设计均未发生源码漂移；唯一清单在施工期间由主线更新，本包没有编辑。详见 [consumption-initial.json](consumption-initial.json) 和 [consumption-final.json](consumption-final.json)。本地消费合同不导入 Build ORM，也不认为“源码可导入”等于真实样件接口冻结。没有抽取旧业务算法/导入旧app或继承旧批准。

未完成与恢复条件：主线须提供真实 SampleUnit/ActualConfiguration、当前身份/资格/受众/原值核对、具名接收/资源和消费端口，再登记实体/迁移/命令/API/路由/BFF，执行 [集中事务和浏览器病例](integration.md)。所有端口需同事务锁定、双对象CAS、证明消费、原子领域/样件/回执/Audit/Outbox；假端口不能替代这些条件。独立TestPlan、扩展补交、新样件/配置、读数纠正/分段、原报告导入、Issue/CAPA及部分请求整体关闭留后续。

本轮没有读取.env/.local凭据、连接或迁移数据库、启动/停止共享服务、安装依赖、运行全量构建、真实模型调用/业务外发、生产/云操作、删除实际资产、git提交或push。测试禁用bytecode/cache后在包内执行；初期标准解释器曾生成普通导入缓存，没有改变公共源码。唯一清单及 G/N/P/Q 状态未由本包修改。

复验命令（仅新增改动/风险时运行）：

```text
# pdos-next/server
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q --confcutdir=tests/verification -p no:cacheprovider tests/verification
.venv/bin/ruff check pdos_next/domain/verification pdos_next/schemas/verification tests/verification --no-cache

# repository root: no typegen / shared .next / incremental cache
pdos-next/web/node_modules/.bin/tsc --project docs/reports/evidence/pdos-next-verification-20261002/tsconfig.check.json --noEmit

# pdos-next/web
node_modules/.bin/eslint src/components/verification
node --test src/components/verification/render.test.mjs
```
