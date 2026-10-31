# Embedding 管理配置与服务商身份检查点

已合入实际平台设置的独立 embedding profile、独立凭据连接及原 T1 预览确认。新增连接复用现有服务器 KMS 写入路径；这里只使用 fakeKMS，没有读取真实 Keychain、凭据或调用真实模型。

服务器统一从受控连接读取 canonical provider，profile 绑定、P26 数据类别协议、后台计划/执行及查询前复核使用同一身份。价格卡保留原始服务商标签。没有用端点 hostname 替代已登记协议身份。

## 实际验证

- [原生回归](pg-canonical-regression-run2.xml)：20/20 通过，覆盖 profile、后台 batch、查询与相关目录路径。
- [新增策略用例第一轮](pg-canonical-policy-run1.xml) 中两项通过；唯一失败为测试通过 Receipt.confirmation_id 寻找通用 T1 确认的错误假设。现按实际 confirmation token hash + tenant/actor/operation 精确读取，原生 consumed/snapshot 检查 [重跑通过](pg-canonical-policy-run2.xml)。三项唯一用例全部有通过证据：限制协议排除计划、排队后收紧拒绝且零占用/费用、真实主模型 READ 零 embedding 与诚实关键词回退。
- canonical/查询/fakeKMS 合计70项纯测通过；前端23项通过；组合 TypeScript 通过，见相邻个人知识检查点的 typecheck-combined-run1.txt。
- 第一轮回归暴露真实 PostgreSQL CTE 标识超过63字节：九来源和八来源名称截断相同。已改为固定前缀加来源集合 SHA256 短指纹，实际检索语义保持；3项 SQL 编译检查和上述20项实际回归通过。失败日志保留。

## 剩余

本次新增 UI 的生产构建及浏览器操作将在 F/G 合入后集中验证。真实 embedding 质量、真实 KMS、ANN 规模和混合检索默认启用没有验收；真实调用仍为零。
