# 第二十一波 · 新共享三人案例的有限宿主配置

本合同只定义当前下一段施工。第二十波封存前不修改运行源码；公共数据库、HTTP、启动与收口验证由主线统一执行。没有生产资格、人工出口或正式业务批准。

## 本段目标与复用

复用现有 issuer registry、固定完成分类、RulePublisher、实际配对 owner 及专业事实保存服务，让服务器能够显式配置多个独立的本地合成产品范围。旧单范围接口兼容；新有限列表明确包括需要继续使用的旧范围及新范围。不能通过覆盖默认 issuer key 将旧 private 材料扩围，也不能由模型、调用者或业务 payload 选择宿主配置。

每类单配置与列表配置互斥。列表为明确非空 list，最多 20 项；先校验全批字段、scope、key、finite ledger 和现 registry 冲突，再登记。完整相同且现 registry 仍指向可信原对象的配置可复用原对象和 epoch；缺原配置依据、撤回或替换对象、同 key 跨范围或同范围矛盾配置拒绝。失败不留下部分登记。当前资格和来源仍在各真实消费阶段重新核对。

## 独立文件归属

- A：operational/test_resource/quality 三个 bootstrap 和各自新增 profile-list 纯检查。新增 `configure_local_profiles(engine, profiles)`；新 operational/resource profile 显式自带独立 issuer key/version，有限决策仍绑定真实 resource、操作、用途及期限。
- B：`quality_followup_integration.py` 及新增 completion-list 纯检查。完成分类按实际 engine、tenant/product、server basis 的 Project 精确分派；未知范围拒绝。旧十二字段及实际 Completion 依据、回执和 ACL 不变。
- C：professional authority 配置与 RulePublisher 及各新增纯检查。新专业 profile 不授真实资格。Rule 的本段配置限制同 tenant/product 只有一个 Project；实际 read/current 再核锚点及保存规则的 Project。dispatcher 的配置身份及任一 issuer epoch 变化必须进入宿主 runtime stamp。
- Root：`api.py`、`asgi.py`、本地启动配置读取与对应接线检查；统一冷导入、影响验证和实际环境检查。网页及配对 owner 不属本段修改范围。

## 下一实际业务案例

新建 Product/Project、已知单行 BOM、工程与制造配置、新 Build、新库存池和专用设备；两件 A 样件分别建立原失败与后续复测。所有资料从首次登记即为合法 `product` 共享，原 private 资料及旧失败链保持。

Maker 办理工程/制造、调查根因、本人完成、回链/候选；Observer 办理品质接收、Run、报告上传/解析登记、原值/结果与 Observation。第三位 IndependentReviewer 仅办理具名 CAPA Review，不参与 Run 执行、报告登记、根因、遏制、措施完成、观察或 Run 复核/处置；这些历史参与者全部仍须由实际 owner 核对。

复用旧 Demo 的提交、实际交接、正式请求、资源、计划/承诺/开测和结果构造算法，需要独立工具、checkpoint 和三套真实登录上下文。原 Demo 固定一人及单产品，不原样运行或替换旧 checkpoint。

来源按 Artifact identity/version 合并，示例预算可为 19 个版本。已真实发生的多个完整原行可登记在一个新的不可变文本；不得预写未来事件、追加旧 Artifact、截断依据或为预算忽略来源。最终以实际完整闭包不超过 20 为准。

本段配置完成不等于新业务案例已通过。独立 Review 可如实保存总体 unknown；非 unknown 调查履行还缺精确绑定调查交付物与验收规则的受控 implementation owner。物理整改、完整观察、真实资格、独立有效性、分别关闭和正式变更实施保持各自真实依据关口。
