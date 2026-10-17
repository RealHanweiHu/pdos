# S4 固定移交包与独立外部回执

本闭环已实现受控人工材料路径：固定实际发布包及两项工程/制造具名决定，核对编号版本映射和文件 manifest，由本人一次共同 T2 保存授权、原发送意图与初始 Current；随后逐条登记可信宿主验证的实际原回执。发送、接收、生效分别读取，保留未知、部分范围、显式对账及冲突历史。**代码没有执行网络发送，S4 未验收。**

依据冻结 v1.1 附录 A/B、S4 合同与确认稿 P13/P21；性能验收暂缓，S1 保持未验收，不增加阶段批准或重复攻防。

## 已有能力

- 实际 owner 读取固定包、明确选择的两项专业决定、共同回执及当前直接水位；不把 DTO、摘要或客户端传入的资格当证明，也不重跑历史签署人的完整专业评估。
- 移交约定明确必需映射和文件集合。编号映射核对真实原生版本关系；文件固定原件版本与内容摘要。缺失集合保持未知，明确空集合仅按实际约定处理。
- 可信宿主核验挑战绑定原件、内容、当前事务和调用人。默认不登记真实 issuer；合成 issuer 仅显式隔离测试可启用。回执发行者与缓存按已保存授权的项目绑定，同产品多个项目使用同一接收方不会借用资格或误报歧义。
- 一份 T2 只消费一次共同确认，期限允许为空；授权、意图及 Current 原子保存。每条回执追加不可变顺序和前驱，Current 只做一步 CAS。发送未知时拒绝新增盲目发送记录，必须显式对账同一原意图。
- 私有 Artifact 或私有上传原件不能用于共享移交记录；实际来源检查在 inputs 阶段即拒绝，数据库受众守卫仍保留。
- 实际页面接通固定材料、三阶段状态、原始回执历史和原请求恢复入口。写入仍走共同 Command；本轮浏览器只读，不将其称为页面 T2 提交验证。

## 候选与验证

| 范围 | 证据与结果 |
| --- | --- |
| 最终实际链 | [actual-chain-final-04.json](actual-chain-final-04.json)、[日志](actual-chain-final-04.log)：同一固定候选、独立实库和实际 HTTP，1 条完整合成病例通过。含实际双专业决定、无期限 T2、共享授权引用私有回执 403 且零移交写入、六条回执、盲目重发 409、显式对账、CN 部分接收→CN/DE 完整接收→生效→摘要冲突、原命令重放零新增及政策撤回后的原政策重放。 |
| 后端纯检查 | [backend-pure-final-03.json](backend-pure-final-03.json)：209 项通过（发布 136、移交 73），不与此前 204/205 项重复累加。 |
| 精确交付副本 | [standalone-delivery-final-03.json](standalone-delivery-final-03.json)：HEAD `f0cb352` 加 38 个精确归属文件，排除无关待提交上下文，209 项通过且数据库连接为零。[候选差异](delivery-candidate-comparison.json)记录三处公共文件的无关上下文剔除，以及 contracts.py 仅拆分导入的格式修正；不宣称实库链在整个精确副本重跑。 |
| 前端 | [frontend-checks.json](frontend-checks.json)：独立 HEAD+8 输入中 34+42=76 个不同检查通过；类型/lint 通过。[production-build-01.json](production-build-01.json)独立生产构建通过，八项输入与最终交付完全一致，后续后端修复未触发重复构建。 |
| 迁移 | 0783 在核对的 `127.0.0.1:64245/pdos_test`、marker `f9048729-3f2a-4494-af75-56e1db7d743d` 上 [up](migration-up-02.json)→[down](migration-down-02.json)→[reup](migration-reup-02.json) 通过；[metadata](metadata-02.json)四表 ORM 无差异、普通属主/FORCE RLS、Agent 无直接权限、app 无 DELETE。有历史后[拒绝降级](downgrade-history-refusal-final.json)，head 仍为 `s0_0783` 且四表记录数不变。 |
| 静态检查 | [static-final.json](static-final.json)：30 个 Python 文件 AST、29 文件正常 lint、冻结 SQL 文本忽略 E501 后 lint、26 文件格式通过。冻结 PostgreSQL 原始函数文本的换行诊断，以及三个共享文件原有前缀格式差异单列，不重排已安装迁移或无关旧代码；冻结迁移末尾空行的 diff 检查诊断保留。 |

迁移前备份保留于私有 `.local/pre-external-handoff-20261017-s0_0782.dump`，68,103,929 字节，SHA256 `7d3576e9df48a2ea7613f4692921dcdf6edf5fca879411b8d990a599f186e936`。未覆盖原工程历史备份。

## 实际页面证据

浏览器使用已存在具名登录和授权、只允许 GET/HEAD/OPTIONS 的临时 API，未新增登录、资格或期限。实际读回同一移交的六条原回执和三阶段：[HTTP 读回](browser-api-read.json)、[桌面 DOM](browser-desktop.log)、[桌面截图](browser-desktop.png)、[320px 暗色](browser-320-dark.png)、[生效冲突局部](browser-effective-320-dark.png)。面板 clientWidth/scrollWidth 同为 252；历史条数为 6。控制台仅既有 favicon 404，见[日志](browser-console.log)。浏览器前后四类移交业务表快照一致的断言已通过。

页面候选为 `_9k6b68_`，早于最终项目绑定和 inputs 私有来源修复；新增 UI 八个输入完全相同。最终两项后端修复由最终实库链和精确副本纯检查覆盖，未冒充最终浏览器写入验证。专属浏览器 Cookie、会话、API、Next 预览及导出凭据已[清理](browser-cleanup.json)，数据库与备份保留。

## 失败与修正记录

- 初次迁移在 CASE 比较括号处失败并回滚；安装前修正后实际往返成功，已安装 0783 未被重写。首次 metadata 检查因私有脚本相对路径错误未执行，第二次通过。
- [actual-chain-01](actual-chain-01.log)：意图插入时父授权尚未 flush，RLS 拒绝，事务回滚；改为按父子顺序 flush，未减弱 RLS。
- [actual-chain-browser-02](actual-chain-browser-02.log)：同字段 OriginalRef/SourceRef 的子类型比较导致 UNKNOWN；统一四字段规范后，版本/位置变化仍拒绝。该次授权/意图已保存，失败历史保留。
- [actual-chain-browser-03](actual-chain-browser-03.log)：六回执链和只读页面已通过，随后旧政策重放失败。原因是夹具中途新增专业原件，扩大政策重放的来源集合；把移交专属资格准备前移到初次政策发布前，保留生产政策守卫。最终第 04 次完整通过，不把第 03 次整链计为通过。
- 初次最终纯检查使用不存在的目录，零测试执行；修正后先 205 项通过，再补项目范围/私有原件病例至最终 209 项。初次静态检查的冻结长 SQL、既有前缀格式及新导入格式诊断保留；只修正本次导入。

## 剩余范围

这是本地合成材料联验，真实模型、KMS、外部发送均为零。真实协议/业务原件、可信外部 issuer、客户接收和外部实际生效资格尚未配置；Worker 网络发送、独立例外/豁免及相应阶段场景继续建设，不据此宣称生产启用或 S4 验收完成。

生命周期目录本轮显式补齐本次四表与已有 S4 八表的字段/守卫库存；另外七个既有表仍未纳入，未知覆盖继续拒绝全局清理，不能宣称全库生命周期清理已就绪。S3 原一天观察与具名评效未缩短，S1/S2/S3 仍未验收；性能暂缓、真实出站、push 与生产批准边界不变。
