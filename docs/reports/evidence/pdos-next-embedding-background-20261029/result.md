# Embedding 后台层检查点 · 2026-10-29

独立 profile、后台批次、费用账本与离线 RRF 已合入；本层最终 **94 项纯测、14 项实际 PostgreSQL/Temporal 检查通过**。真实模型、embedding 与业务外发均未调用。完整两份设计继续进行。

## 可用能力

- 当前本人租户管理员经原 COMMON T1 预览、确认、Receipt/Audit/Outbox 保存独立 embedding profile、选材与租户索引预算。保存不调用提供器，不借用聊天凭据。元数据 GET 在普通只读快照核对当前管理员。
- 真实 Outbox → Temporal Activity → 注册的小Pai LangGraph → 固定有界批次。每次读取复核实际来源、版本、hash、扫描、权限和 P26；客户原件默认排除，单独确认后才能纳入。来源重建与批次重放保留原费用。
- 费用从用户 Run 预算分离。进程丢失、unknown 标志或超出计量上界时按原预占保守记账；具名 T1 对账不重发旧调用。有限重试、实际 Worker 重启和提交后 ACK 丢失均有验证。
- 同一权威过滤用于关键词/向量候选，固定维度有限值与单位向量校验、确定性 RRF、换版隔离及停用回退。页面读取不触发 query embedding，默认检索仍为关键词。

## 最终证据

- [实际 PG/Temporal 14/14](pg-background-final-run6.xml)，47.57 秒；[原始输出](../pdos-next-assistant-combined-20261029/pg-embedding-background-final-run6.txt)。包含默认/客户原件显式选择、普通角色私有来源隔离、换版/停用、重复任务/实际 Worker 重启、未知对账、凭据轮换/预算/撤回前置拒绝、未知与越界计量、实际管理员及旧关键词/生命周期相容性。
- [纯测 94/94](pure-background-final-run4.xml)，2.18 秒；[输出](pure-background-final-run4.txt)。涵盖源字段映射与正式迁移 DDL、有限向量、提供器协议、固定过滤、RRF、原关键词、命令/合同与生命周期目录。
- 53502 / `pdos_test`，标记 `f117bb5b-b3d7-4286-aaec-c54d9255e96b`，当前 head **s0_0837**。0836 前备份 98,146,506 字节，0837 前备份 98,239,533 字节，均在本项目 `.local/`，SHA 见各记录。[0836 往返](migration-0836.json)、[0837 往返](migration-0837.json)均成功，已比较历史计数不变；[非空降级拒绝](migration-nonempty-downgrade-refused.json)后 head、费用/来源数据及内部调用权限完整保留。
- pgvector 0.8.6 实际安装，六表 FORCE RLS，六个维度的 partial HNSW 索引实际建立。维护角色 NOLOGIN，运行角色无其成员权及停用 helper EXECUTE，维护角色无原始 vector SELECT。只有原 schema owner 的确认触发器可调用停用 helper。
- [39 项最终改动输入](final-source-sha256.json)、[2710 项候选输入](candidate-background-inputs.json)、[精确合入清单](application-manifest.json)、[根集成差量](root-integration-delta.json)。前端输入未变，沿用此前对应的 719 输入构建与页面证据，本层无新增管理页面。
- [Ruff 定向通过](ruff-background-final.txt)、[diff 检查](diff-check-final.txt)；两个共享文件的既有风格项见[基线](ruff-existing-shared-baseline.json)，不冒充全库 lint 通过。[合同导出](contracts-export-final.txt)为 128 个实际 payload，[校验](contracts-validate-final.txt)通过；新登记两项 T1 及事件，规范操作/阶段验收数未扩改。

## 集成中发现并修正

两张模型表的继承声明遮蔽导致 ORM/DDL 都漏 category_id；测试误依赖临时 stage 模块；既有依赖函数需要 Select 而非 CTE；只读 GET 错用带 FOR SHARE 的写入管理员守卫；ALTER OWNER 后原 owner 的内部 EXECUTE 消失；包装 Engine 丢失实际扫描配置。原始失败输出保留，最终通过不累计旧失败和重复运行。0837 用后继迁移修复权限，未改写已执行的 0836 SQL。

## 剩余范围

Run 内 query embedding 的独立绑定/占账/取消/恢复接线与管理 UI 正在继续。小样本的 exact/iterative SQL 均执行过，但未提供真实 planner/ANN 规模召回或质量结论；索引存在不等于已证明 ANN 使用及收益。真实 embedding、同版人工问题集比较和默认混合启用仍未执行，本层合成结果不授予真实质量资格。
