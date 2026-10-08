# Wave7 · 人工验证准备与品质缺项

本轮承接已完成的固定Build、实际配置/批次/样件和供应/成本。目标为用户可保存与续版的验证准备：要求、方法候选、资料、数量/模穴、期望返回和暂定时点；历史、精确来源、缺项、下一步条件可回查。唯一活动状态仍在 tasks/ai-native-integrated-todo.md。

## 实际前置与政策

2026-10-02只读核对：主线Build为planned；真实SampleUnit只有unknown/hold，缺物理就绪、方法适用性、专业职责/人员资格、设备校准和资源/样件预约消耗端口。产品写权限不能转换成quality/test职责与qualified=True；批次产出时间不能充当样件就绪时间。

本轮新增辅助具名人工T1 `verification.preparation.record`，只保存人工准备草稿。复用共同实质预览与一次确认，包含整版前后、来源和缺项；没有独立确认/回执事务。原canonical verification.request.create/schedule.propose/handoff与test操作不因这次辅助记录获得资格或开放。方法资料齐全不等于专业方法批准；暂定时间不等于接收、承诺、正式预约或实际开测。准备版本status=prepared、所固定请求status=draft，交样/接收/运行/结果事实为空，缺项明确保持。

## 交付与并行归属

- 领域执行者独占新 `domain/verification_execution/{__init__,models,schemas,service}.py`：不可变准备版本、逻辑请求当前指针、完整来源检查、差异/缺项、读模型。旧verification DTO/document_gaps/coverage_gaps只读复用，不实例化虚假Authority或安全端口。
- 验证执行者独占 `server/tests/test_verification_execution.py`：真实持久Build/Sample夹具、权限/来源、T1、幂等、CAS/并发、事务与历史/数据库守卫。公共数据库与联合验证由主线执行。
- 界面执行者独占 `builds/build-verification.tsx`、`lib/build-verification-view.ts`：精确引用表单、整版确认/恢复、历史和缺项；实际样件仅参考，正式接收/开测/导入呈现明确阻塞。
- 主线独占公共注册/API/BFF/页面、next_0009迁移、环境与集中证据。旧工程未提交工作、其他会话目录和状态不改写。

## 验证与边界

仅操作经容器身份和marker双核对的127.0.0.1:62513/pdos_test，marker 916f950f-2d2b-405d-b809-c15db75dc20c；实施前实际head=next_0008。先保留私有备份，业务数据写入前迁移往返；随后最小受影响测试、一次冻结联合回归、schema/生产构建及真实页面两版准备流程。旧包检查数不加入主线通过数。

本波不能宣称正式品质接收、TestRun、测量导入、破坏性样件消耗、真实资源资格或AT-11/13/14/15全量通过。恢复条件为后续接入可信职责/人员资格、实际执行/样件就绪适用性、资源与消费、原件数值核验，保持共同事务与具名决定边界。文件扫描与原件生命周期仍是独立待汇合工作，不将其包内通过写成主线已集成。

没有真实模型调用、业务外发、生产操作或git push。保留9/27备份基线0377之后部分登录/序列不可完整重建的历史边界。
