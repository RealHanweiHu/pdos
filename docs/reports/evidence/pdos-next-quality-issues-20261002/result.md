# G3.1 问题/CAPA 独立首版交付

2026-10-02，独立首版已实现并通过适当局部检查，尚未接入主线真实业务入口。所有源码写入仅在四个 quality_issues 独占目录；证据在本目录。没有修改唯一清单、公共模型/迁移/注册/API/BFF/父页面或其他业务包，没有提交/push。

可调用入口为 `QualityIssueHandler.preview/execute`、`QualityIssueReader.get`、封闭 DTO、服务器 ports 和四个独立前端组件。真实TestRun/事件/资格/政策或端口缺失时明确 INTEGRATION_REQUIRED/当前不可办理，不注入fixture、不返回模拟成功。固定测量原值由品质TestRun只读解析，不建第二份测试结果。

已完成：

- 稳定失败身份独立于event/key/title/Run无关revision；真实事件核验、同事件多个独立失败映射、跨key同意图只建一单；重复不再发issue.created。
- 精确Run/测量/样件/判据/方法/配置/原值来源固定，确定性复算拒绝unknown/空/计划结果和不一致实际时序；源修正/撤回与配置变化留原历史、当前判断待重核。
- T1实质归并保留原Issue、全部失败/alias/遏制/历史；范围/受众/CAS/已有整改和专业结论冲突拒绝。
- open→triaged→actioning→awaiting_verification→closed；遏制与执行事实、根因假设与具名结论、CAPA草稿与真实措施完成分层。措施完成不等于有效/关闭。
- 服务器风险/独立政策、CAPA要求摘要、整改后的完整观察窗口、新固定Run精确覆盖；原/新测试、遏制、整改执行者及根因决定者不可自证独立有效，AI拒绝T2。有效性决定和关闭为分别具名办理，旧无效/有效决定完整保留。
- 只读历史与不可用来源、权限/配置漂移、过期/编辑预览、未知回执恢复、nullable原值与失效来源隐藏；共享确认/回执由主线负责，不新增命令平台。Change/Build/Run只输出后续需求。

最终局部验证：

| 范围 | 结果 | 原始证据 |
|---|---|---|
| 后端纯合成，插件/bytecode/cache禁用、confcutdir本包 | **110 passed** | [backend-final.log](backend-final.log) |
| 本包后端/schema/tests Ruff，无cache | 通过 | [ruff-final.log](ruff-final.log) |
| 前端合成契约/静态渲染守卫 | **25 passed** | [ui-tests.log](ui-tests.log) |
| 本包TypeScript，noEmit/nonincremental | 通过 | [ui-typecheck.log](ui-typecheck.log) |
| 本包ESLint | 通过 | [ui-eslint.log](ui-eslint.log) |

测试包含caller事务stub在proof消费、插入、归并中途、delivery/receipt/outbox写入阶段抛错后的全部回滚；这些是假端口契约检查，不证明真实DB事务。初期fixture接口诊断、lint/TS诊断，以及最终追加混合性质守卫带来的错误分类诊断均保留原始日志，已在独占目录修复并通过最终检查。

21份包内源码/测试/配置候选SHA256：`1bf5e8a83273c61e65a8f4cd74f71c29a7c5fc0c1110cc751d714a9922e68b1e`。文件逐项摘要见[candidate.json](candidate.json)，检查命令/结果见[validation.json](validation.json)。前端10文件独立候选见[ui-candidate.json](ui-candidate.json)。消费接口初始/最终摘要已保存；运行接口无漂移，唯一清单由协调会话更新至第五波及新并行窗口，已定向重读，[consumption-final.json](consumption-final.json)记录变化与判断。

未完成/阻塞条件：主线持久层、归档TestRun/原值/事件与资源适配、真实职责/资格和PolicyPort、共同事务/注册/API/页面接线，DB/RLS/迁移/HTTP/浏览器联合检查仍未接入。canonical四动作以外的六个包内动作均为拟注册候选；未继承旧批准或授真实T0/T2。无效CAPA后的追加措施/修订、新配置采用、重新解释已撤回原依据需另行版本化合同；首版保留待验证/待重核，不能篡改完成记录或旧决定。

接线清单、CAS/唯一性、异常病例与实际DTO映射见[integration.md](integration.md)及[ui-integration.md](ui-integration.md)。本次未连接任何数据库、不读.env/.local/凭据、不启停共享服务、不写共享.next、不安装依赖/全量构建，不调用真实模型或进行业务外发/云/生产/现有原件操作。独立包检查不冒充G/N/P/Q联合验收或人工Exit。
