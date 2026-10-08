# Wave21 共享三人案例：实际 Foundation 入口与后续边界

本工具已实现第一段的实际调用路径，尚未执行数据库或 HTTP；后续步骤是明确的交接骨架。Root 负责应用、确认真实目标、审阅预览和集中执行。暂存实现不计入 Wave20/21 的运行成功证据。

## 1. 两种明确布局与只读依赖

- 当前源：`pdos-next/.local/wave21-case-staged/wave21_shared_case.py`。
- Root 迁入位置：`pdos-next/tools/wave21_shared_case.py`；工具仅接受这两种布局，均准确找到 `pdos-next`。
- 新 pure test 的未来位置是 `pdos-next/tools/tests/test_wave21_shared_case.py`；暂存同目录读取 sibling tool，真实 tools/tests 读取父 tools 的实际 tool，server/tools ROOT 取该被选模块的真实 ROOT，不能把 test 所在目录误当源码目录。
- 只复用 `tools/wave15_seed.py` 的真实源定义：canonical、merge_reads、subject_revision、private_write、checked/安全错误码。不会实例化旧 Demo，不读取、修改旧 seed/checkpoint/issuer/profile。
- 导入阶段只有 Python 定义；`--phase plan` 不初始化 target、Engine、Client 或 checkpoint。
- Foundation 执行阶段每个 DB/HTTP 边界用真实 `verified(read_state())` 校验显式 marker、62513 和原目标 tenant，不回退 `.env`，不复用 preview Product。

## 2. 第一段实际执行顺序

1. 全新私有 checkpoint 先持久化 case UUID、三个不同人类 UUID/登录 token、固定登录/同伴 Grant 截止时点，再触外部边界。
2. 一次真实 admin UOW 为这三个新身份创建 Principal/LoginSession。已有记录必须精确匹配，不能补缺失一半、延长期限或修复停用状态。这只是明确本地合成身份 bootstrap，不授专业资格。
3. Maker 用实际 `POST /v1/products` 保存全新 Product（服务器分配 ID；真实 ProductInput/幂等键/Receipt）。该 API 是已有真实入口，不伪造成 common Command。
4. 同一新 Product 的 Observer/Reviewer Grant 在真实 admin UOW 受控创建；Maker 必须拥有 API 创建且有效的真实 Grant。不改旧 Product/Issue 或旧 private ACL。
5. Maker 依次保存 native Artifact、Definition、Project、已知单 BOM、EngineeringConfiguration、ProcessRevision；所有 payload 从首次保存均为 `visibility='product'`，Project 属于 Maker。
6. 每个 common 操作按当时真实 T1/T2 注册表处理：T1 真实 preview 后停止，只有相同 label 的 `--confirm` 才提交一次；T2 不由 Foundation 代办。当前 native register / definition draft 是 T0，project / BOM / engineering / manufacturing 是 T1，不凭名称硬编码例外。
7. 三人分别通过实际 workspace / definitions / projects / configurations GET 核同一共享源与固定版本；只有全部成功才保存 `foundation_saved_not_build_started`。

实际 families：`product`、`artifact`、`definition_revision`、`project`、`bom_revision`、`engineering_configuration`、`process_revision`。Receipt 必须是实际 JSON 的 `id`、精确 operation/family/subject/revision、Maker writer/requester，flattened result.id/revision 一致。

源文本校验使用真实 `pdos_next.service.digest(content)` 与 Artifact.content_hash 对照，另列 raw UTF-8 SHA，不假定两算法。Project 来源状态读取 `row.definition.source_status`，同时核 fixed Definition ID/revision 和 Maker owner/purpose；其余 Definition/配置读取实际 top-level source_status。来源 `status='active'` 与配置 `source_status='current'` 不互换。

## 3. 原请求、一次确认和 UNKNOWN 恢复

- 每个 label 首次构造真实 typed Command，命令 UUID5/key 固定，先保存 actor_id、Product、完整 payload/readset 原顺序和原 Product expected_revision。新命令才读 live Product revision。
- 已保存 label 先校验固定 operation/family/actual actor/原 Product/key/command 与实际 Receipt，直接返回旧保存结果；不先重构 workspace/version。
- 未保存但已有原 Command，输入必须与原 actor/Product/payload/readset/顺序/key 完整相等。原 expected_revision 直接保留，当前漂移由真实共同入口判断，不能本地换版本。
- 真 preview 返回的 Command 要保持原实质材料，确认 token 仅存在 0600 checkpoint。每次 invocation 至多确认一个精确 label；正文按原真实 prepared Command 一次提交，非重造 JSON。
- 发送前先持久 `sending`；传输异常标 UNKNOWN。后续普通 invocation 不重试，明确 `--recover LABEL` 仅发送同一原 Command/token/key 一次。实际公共入口若已写，返回旧 Receipt；若令牌过期或当前门禁拒绝，保留原请求并报告，不补 token/预览。
- preview 本身传输未知保存 `preview_unknown`，不给替换 token。需要按实际恢复合同处理，工具不假定 preview 未发生。
- actual domain 错误只记录安全 status/code；不输出错误原文、token、URL 密码或原命令。保存正文/token 漂移检测失败，保持旧 intent。

## 4. Root 执行方式（本交付未执行）

在 `pdos-next` 下，用显式真实 marker；初次应停在 project 的真实预览。每个预览退出 2 是待确认，并非业务完成。

```text
PYTHONPATH=server:tools server/.venv/bin/python tools/wave21_shared_case.py --phase foundation --marker <actual-marker>
PYTHONPATH=server:tools server/.venv/bin/python tools/wave21_shared_case.py --phase foundation --marker <actual-marker> --confirm project
PYTHONPATH=server:tools server/.venv/bin/python tools/wave21_shared_case.py --phase foundation --marker <actual-marker> --confirm bom
PYTHONPATH=server:tools server/.venv/bin/python tools/wave21_shared_case.py --phase foundation --marker <actual-marker> --confirm engineering
PYTHONPATH=server:tools server/.venv/bin/python tools/wave21_shared_case.py --phase foundation --marker <actual-marker> --confirm manufacturing
```

也可直接运行当前暂存路径。`--recover LABEL` 与 `--confirm` 互斥；UNKNOWN 退出 3，明确依赖/拒绝退出 1。输出只含当前状态、已保存数与真实 review/到期时点，token 不打印。服务缺注册/权限/专业/原件端口不由工具修复。

## 5. 新 checkpoint 的冻结消费字段

仅 `pdos-next/.local/wave21-shared-case.json`，必须当前用户所有的 regular 0600 文件，拒 symlink；安全临时文件原子替换。无旧 seed 覆盖。

```text
schema_version='wave21-shared-foundation-v1'
marker,tenant_id,case_id,purpose,visibility='product',created_at,bootstrap_expires_at
actors.{maker,observer,independent_reviewer}={id,login_token}  # 私有不报告
requests[label]={role,actor_id,original?,body,state,preview?,last_error?}
receipts[label]=actual Receipt JSON
product_id,project_id
scope={tenant_id,product_id,project_id}
configuration={bom_id,bom_revision,engineering_id,engineering_revision,
               manufacturing_id,manufacturing_revision}
sources.foundation={reference:{artifact_id,expected_revision,line,quote},
                    required_source_read_set:[{artifact_id,expected_revision}]}
readback.{each_role}={shared_objects:6,stored_content_hash,raw_text_sha256,
                      professional_qualification:null}
phase='foundation_saved_not_build_started'
```

Definition ID/revision 从 `receipts.definition.subject_id/subject_revision` 取。三组 token 仅供对应 actor 实际 API 入口，不能代作 Owner Context。bootstrap_expires_at 是登录/同伴 Grant 的有限期，不是专业资格/政策有效期。此段没有任何 issuer/profile 注册、Build/Run/Issue 创建，后续必须先实际导入当前完整职责和有限多 scope profile。

## 6. 后续业务分工与最小可推进顺序（未运行）

- Maker：工程/制造职责、计划数量 2 ea 的新 Build、已知 BOM 需求/物料与资源事实、双 T2、实际 Start/Actual/Lot、两件不同 A Sample、具名 ready/offer；当前失败 Issue/遏制/CAPA/root cause/本人调查完成/回链/候选。RootCause/Rule 还需要该实际人的 quality 当前事实；Grant 不代替资格。
- Observer：两条不同 Formal 请求与实际方法/接受、Plan/Promise、各自实际 Start/原报告上传/原值导入/compute；真实分别 Run Review/Disposition；完整 Observation 实际记录。原报告登记人也是参与者，不能留给第三人。
- 第三人：仅具名独立 CAPA Review。不得参加原测试/报告/根因/遏制/措施完成/新 Run/测量/Observation 或 Run Review/Disposition。必须真正读得到共享全部来源；旧 private Case 不扩围、不 clone 同 Failure。
- 最短续接：真实有限专业/profile 全部在 Start 前登记 → Build 与两件不同 Sample → 原 Request/ActualMethod/Accepted/Run/失败 report → Issue/CAPA/root cause/本人调查完成 → 新 Request/ActualMethod/Accepted/不同 Sample/独立实际 Run/报告/分别 review+disposition → 正确 paired Current 输出回链+候选 → host Rule/完整 Observation → 独立具名 Review。
- 法定操作沿真实 registry：`build.configuration.actual.record`、`build.output.record`、`build.sample.allocate`；不发明影子操作。实际 T2 由既有具名入口办理，本工具不自动签核。
- 新 Run/资源窗与样件用量从真实 owner/统一占用账得出，原始和复验各用一件实际 A Sample，不能重用已 consumed 样件；新 report 必须真实 Original 上传/scan/parse/精确原值，native 文本不能冒充仪器原报告。
- Formal 经 Promise/Start/Result/Review/Disposition 后必须使用实际 paired owner 的精确 Current/LaunchFact/ResultAction/Run Receipt 证明。旧 Draft Link 只是历史计划，不能冒充当前后继；domain intent 与 common intent 分别校核。

## 7. SourceRead 完整闭包与仍缺的依据

每 phase 从真实 owner 取全部原 Failure/report/retained Build/config/Sample、root/完成/分类/要求、当前 paired Method/Criterion/实际报告、Rule/Observation、专业/政策/issuer 来源 readset 并集。用 actual merge_reads 严格冲突检查与上限 20；不截断、不删 raw refs/locators/safety epoch。空的“未知 owner 组”不能默认为已齐；单纯 declared union 不证明 actual completeness。

降低数量只能在首次注册时把同一真实已发生材料或固定出版的完整原文行放入一个新不可变共享 Artifact；不能预写未来事件、追加/替换旧 Artifact、丢任何实际闭包来满足上限。实际安全来源是否 19/20 需集中测量，工具没有声称预定预算通过。

真实调查 CompletionFact 仍须明确已发生 aware clock/IANA 与精确 9 字段原文；12 字段受控 classification 只证明 investigation，不证明物理整改/行动履行。实现端口不足时 action fulfillment 保留 unknown。总体 unknown T2 Review 也必须完成真实候选、完整 pair/action 映射、Rule、Observation、专业/政策/参与者独立性/来源新鲜度核验，不因为 unknown 少门禁。Effectiveness/Close 本段不建设、不授通过。

## 8. 自有验证边界

新测试只跑 `--noconftest` 单文件，禁止 Engine.connect/raw_connection、httpx.Client.request、target/bootstrap/grants；明确 HTTP 响应替身只验证 retained 原请求控制。实际 PAYLOADS、当前 T1/T2 集合、配置 family 表和纯 seed 算法直接复用。另做 Ruff/format/AST 与 offline plan；没有 DB/HTTP/服务/browser/public pytest/build，不能称 Foundation 实际成功。
