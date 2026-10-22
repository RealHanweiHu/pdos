# 需求与机会、发布规格的双向来源

2026-09-30，0406工作树。按完整合同§7与N1-04/N1-06核对关系和实际传递；未将后续Case/Project完整启动出口纳入本次结论。

## 修复

复用既有需求时，`definition_intake._inspect`把标题、描述、验收标准分别传给只接收整行映射的`_plain`，实际接口发生ValueError，新建路径不触发此问题。现在直接比较已存储的标量/JSON列表与建议字段，继续要求明确确认差异，复用仅关联原需求。首次失败见[原日志](../../../../output/pm-requirement-relations-0406/definition-sources.log)，修复后见[实际接口整链](../../../../output/pm-requirement-relations-0406/definition-sources-final.log)。另补三处返回类型声明，运行行为不变。

## 已验证范围

- [机会关系](../../../../output/pm-requirement-relations-0406/backend.log)：1项实际整链通过。两项需求各关联两个机会；原请求重试不重复建立关系。需求修订后原快照不变且标变化；机会修订可明确保留原需求版本、去掉新版本中的另一关联或重选当前需求。反向来源保留旧版本并正确区分当前/历史。跨租户、重复及陈旧的新引用拒绝；事件写入失败时机会、关系和事件整体回滚。撤销产品线权限后反向来源隐藏，直接读取机会拒绝。
- [发布规格传递](../../../../output/pm-requirement-relations-0406/definition-sources-final.log)：1项实际整链通过。候选接受和独立应用分开，接受不创建需求；实际应用生成带稳定pressure条目、数值/单位/工况的draft需求，重试不重复创建。另一产品定义经差异确认可复用同一需求，原需求正文保持不变。定义新版发布后已接受的旧包拒绝应用；新版本可另建关联，原100和新110规格快照均保留。需求更新时三条来源均提示变化；跨租户复用拒绝，撤销产品线权限后来源隐藏及包读取拒绝。
- [回执](../../../../output/pm-requirement-relations-0406/validated-receipts.json)：5包、3定义规格关联、Project与模型调用均0。[受影响类型检查](../../../../output/pm-requirement-relations-0406/mypy-final.log)4文件与[lint](../../../../output/pm-requirement-relations-0406/ruff.log)通过。首次类型检查暴露三处已有Any返回标注缺项，补类型声明后通过；未重复运行前端构建，页面代码与[0406矩阵回链](matrix-followthrough-0406.md)构建候选相同。

## 环境与限制

只用独立57434/pdos_test，清理前[完整备份](../../../../output/pm-requirement-relations-0406/pre-tests.dump)，本次传递样本另存[完整备份](../../../../output/pm-requirement-relations-0406/validated-definition-sources.dump)及关系JSON。已恢复原五版矩阵输入、结果、摘要、版本链和时间，head保持0406：[恢复](../../../../output/pm-requirement-relations-0406/restore.log)、[核对](../../../../output/pm-requirement-relations-0406/restore-verification.json)。57434不是空库；无API/页面/浏览器进程遗留。

本次验证实际领域流程，但材料、角色和批准均为隔离合成数据。真实研究、逐能力真实模型评测/资格、RFQ四类原名称、真实专业签核及人工Exit仍待原条件。N项保持部分完成，本证据不替代正式联合门禁。
