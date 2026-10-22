# 消费接口摘要与最终复核

初始读取只限新工程接口和合同，逐文件SHA-256见 consumption-initial.json；最终见 consumption-final.json 和 consumption-drift.json。

运行时直接复用：verification.contracts.DTO（extra=forbid/frozen）、Scope（tenant/product/project）、SourceRef（固定id/revision/kind/position）、Key/Text/Revision，以及标准 DomainError。没有导入旧app，也未导入现有配置/Build/供应/Issue服务作第二写入口。

只读借鉴：
- quality_issues.contracts/ports/integration：Issue/CAPA按聚合版本固定、TestRun原值唯一所有者、来源/当前性与具名独立性、共同confirm/record同事务，不创建或修改这些对象。
- configurations.schemas/service：固定Definition/Spec/BOM/Part/双配置，external设计引用必须固定来源；现有ProcessOperation已有SOP/资源要求，但完整Tooling/Fixture/ControlPlan/PilotRun连接不能补造。
- build_execution.schemas/service：实际配置、BuildLot和Sample身份与计划配置分离，现有输出由所有者创建，不将ChangeIntent冒充实际新对象。
- supply_cost.ports：调用者uow/SAME固定Build双配置与来源、owner快照/currentness/受众、防无来源complete，ERP库存/真实切换由权威端口核验。
- 共同contracts.Command：command_id/idempotency_key/operation/product_id/expected_revision/source_read_set/payload。公共Product expected_revision仍正整数；本包create=0只用于领域wrapper，不改公共信封。

最终复核发现一个共同文件有漂移：contracts.py增加 verification_execution.schemas 的PreparationRecordPayload及 verification.preparation.record 注册（189～194行）。本包消费的Command/SourceRead封闭信封未变化；本包不运行时导入该文件，不受新增注册影响。本包的10个动作仍未被公共注册；主线接线前应再核对共同目录。其余后端消费文件初始/最终hash相同。

前端既有Button/UI基线/参考共同预览接口无漂移，详见ui-consumption-initial/final.json。本包schema/ports/handler最终接口hash另记ui-backend-interface-final.json，包括graph_snapshot本身当前性、来源到目标受众授权、reconciles_id受控对账及record最终锁/读集/取消重验合同。UI只提交固定owner fact_id/item_id，不上载资格/权限/实际结果标志。

主线共同文件持续施工，因此本摘要不声称冻结共享树；固定候选只包含本包18份独占源码/测试/组件文件。
