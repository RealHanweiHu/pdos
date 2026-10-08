# Wave22 新共享制造链：独立可执行工具合同

工具已有实际调用路径，尚未执行 DB、HTTP、服务重启或浏览器。Root 统一核目标、应用、配置和办理；此交付只证明离线协议与当前纯 schema 相容，不证明专业资格、准备通过、库存可用、开工或样件实际已保存。

## 入口及精确范围

当前源为本目录 `wave22_shared_build.py`，Root 可迁入 `pdos-next/tools/wave22_shared_build.py`；两种布局均由真正 `pdos-next/server/pdos_next` 定位。导入工具只有定义，不读取 runtime、seed/checkpoint，也不建立 Engine/Client。没有导入或实例化旧 `Demo`，没有旧 private、旧 seed/profile/checkpoint 的读取或续写。算法依据 `tools/wave15_seed.py` 的 prepare/operational/physical 和现行真实 payload/registry；共同确认不沿用旧 seed 自动确认行为。

仅消费 `pdos-next/.local/wave21-shared-case.json`：当前用户 regular 0600、非 symlink，必须 `wave21-shared-foundation-v1`、同显式 marker、visibility product、三不同真实角色 ID、精确 Scope/已保存配置 Receipt、完整原生来源和三人 6 对象 readback。phase 必须 `foundation_saved_not_build_started`，未完成 Foundation 明确拒绝。Maker 必须真实 Project owner；专业职责/资格由 Root 另外导入，Grant、bootstrap_expires_at 和此工具不授专业资格。

新私有 checkpoint 固定为本目录 `checkpoint.json`；专用制造设备 UUID、新库存池和现场 key 初次分配后固定。`operational-profile.json` 仅此新范围明确有限 issuer，供 Root 追加到原 plural 配置列表；工具不修改 asgi、原配置文件或原 issuer。文件均 0600，目录 0700，新锁文件拒绝 symlink，命令保持同实例串行。

每个实际 DB/HTTP 边界先真实 `verified(read_state())`，仅显式相同 marker 的 62513。HTTP 固定 localhost 8898、trust_env=false、禁止 redirect、单次请求/180 秒，不从 `.env` 或旧 preview scope 回退。工具本轮未调用这些边界。

## 实际已实现的调用顺序

1. `plan`：Maker 实际 GET workspace/projects/configurations，核 Project 的真实 `definition.source_status`（不是 top-level）、固定 Definition/BOM/工程/制造链、owner/可见性及完整 reads。`build.create` T1 创建 2 ea prototype；真实预览后停止，再精确确认一次。随后 T0 `build.readiness.compute` 保存固定需求/缺项，此 legacy 结果 unknown 不当开工批准。
2. `operational`：要求 Root 显式提供已观察 synthetic 余额时点和正执行窗（不得把未来观察保存为事实），从本 Build 实际需求读取新 Part 身份，要求唯一已知需求恰为 1×2 ea。新独立库存池 on_hand 2 ea、available/released、完整 external holds；专用合成制造设备容量 1、完整日历与无外部占用、明确 acceptance/calibration 两份合成具名 ledger。所有材料先固定完整 JSON 行和新 named decision IDs，注册不可变共享 Artifact 后 typed `FactInput`；真实 `configure_local_profiles` 与 `import_operational_fact` 产生共用 Receipt/Audit/Outbox。这是受控本地合成 host 路径，既不冒充真正上产设备，也不授生产资格。未知/失败保留相同 import key/command；只有 `--recover operational` 再办同请求。
3. Root 把 `operational-profile.json` 原样纳入实际 API 的明确 plural 配置，并完成 Maker 工程/制造职责和 qualification 来源导入，再 `assess`。真实 POST `build-start/assessment-inputs` 取当前整个 scope reads；仅实际 `candidate_ready=true` 才发送 T0 带 execution_scope 的 readiness 命令。缺 profile/材料/资格停止，不把原缺项分数改成通过。
4. `engineering`、`manufacturing` 分开读取真实各自 capability，使用外部显式专业适用材料与四项 closed controls。工具不默认生成 applicable。各自真实 T2 预览必须 write_tier=T2/named_decision=true/approval_token，分别停下等待具名确认。首版 null/0，fixed assessment ID/revision/SHA，valid_until 覆盖固定窗口。不是 T1 确认，不等于全面正式放行。
5. `start`：Root 仅给已发生的内部合成实际开工 JSON；工具不填 now，不从计划或旧产出推断。整行必须严格 `{build_id,purpose,engineering_configuration_id,manufacturing_configuration_id,occurred_at}` 与当前新轮次精确对应。注册新共享原文后 T1，实际服务器继续核当前两份批准、窗口/来源/专业事实及原子物料保留/资源占用。
6. `actual`：给已发生精确 `{build_id,engineering_configuration_id,manufacturing_configuration_id,occurred_at}`，真实 server compare 必须无差异/source current；T1 保存同计划 Actual，只是观察，不是资格发布。
7. `lot`：给已观察 `{build_id,actual_configuration_id,observed_unit_count:2,unit:'ea',nature:'synthetic',occurred_at}`；时钟不得早于实际配置/开工。T1 记录明确两件离散产出，server received_at 不传。`samples` T1 从该批创建两个不同 A 单件身份，原 Sample.availability 保持 unknown。
8. 可选但已实现 `ready`：材料是两份已经发生的 strict sample ready event（见下方格式），同一新 Artifact 两条原文。每件分别真实制造专业 capability、T1 一次确认/首版或当前 CAS；原 Sample.availability 不覆盖，不等于交样/品质接受/测试资格。
9. `readback`：只读取本链精确保存的 Build/Start/Actual/Lot/Allocation/两 Sample/两 ready Receipt 对应数据，核 product/current/source 和当时 purpose-specific ready。导出 `continuation` 给 B；这些是带 readback_at 的只读回读材料，B 必须以 Observer 当前权限重新 GET/核 owner，不能借 Maker qualifier 或缓存当持续当前资格。

旧 Build、旧 Run/Measurement/结果、旧资源和旧 Sample 都不修改。工具没有 Formal、RunPlan/Promise/Start、原报告/结果、Issue/CAPA、有效性、关闭或外发功能。

## Root 调用与人工材料

本交付未执行下面命令。示例里的 marker、时间、引用、摘要只能换成该新案例真正值，不能照抄固定未来日期。

```text
server/.venv/bin/python .local/wave22-build-staged/wave22_shared_build.py plan --marker <actual-marker>
server/.venv/bin/python .local/wave22-build-staged/wave22_shared_build.py plan --marker <actual-marker> --confirm build --review-digest <exact-private-review-digest>
server/.venv/bin/python .local/wave22-build-staged/wave22_shared_build.py operational --marker <actual-marker> --material <owned0600-observation.json>
# Root reload exact new operational plural + current professional profile before assessment.
server/.venv/bin/python .local/wave22-build-staged/wave22_shared_build.py assess --marker <actual-marker>
server/.venv/bin/python .local/wave22-build-staged/wave22_shared_build.py engineering --marker <actual-marker> --material <owned0600-engineering-decision.json>
server/.venv/bin/python .local/wave22-build-staged/wave22_shared_build.py engineering --marker <actual-marker> --confirm approve-engineering --review-digest <exact-private-review-digest>
# manufacturing follows the separate approve-manufacturing label and own full material.
# start/actual/lot each first take already-occurred material, then confirm their exact label.
# samples has no client clock; ready-A1/ready-A2 are confirmed separately.
server/.venv/bin/python .local/wave22-build-staged/wave22_shared_build.py readback --marker <actual-marker>
```

Operational material exact keys：`observed_at`, `window_start`, `window_end`, `ack_local_synthetic:true`。它仅配置明确 synthetic 记录；真实权威与生产检查仍由真正 host 决定。

Professional material exact keys：`professional_assessments`, `accepted_controls`, `sources`, `reason`。工程 rule 顺序 product_definition_applicability/verification_objective_applicability；制造 process_configuration_applicability/output_disposition_applicability。每项 status、sources、valid_until、reason 都必须明确，sources 精确引用当前真正原文。四条 controls 不能漏项/重复。T2 确认时原完整 prepared command 和实质预览保持。

Ready material：`{events:[eventA1,eventA2]}`；每 event 精确 keys `sample_id,lot_id,actual_configuration_id,build_id,state:'ready',purpose,occurred_at`。sample/lot/actual 只用前阶段服务器真实 ID，不能提前编造。UTC 为本工具显式窗口/发生时区；原 ISO offset、完整微秒字符串保留在原文，typed server 如 +00:00→Z 只按同微秒 instant 比较，不重写原文。

## UNKNOWN、拒绝与刷新

首次新 common command 读真实 Product revision，UUID command/key 与完整 typed payload/readset 在发送前保存。准备/原请求/预览/Receipt 都在新私有 checkpoint。preview 回来的 Command 必须外层完全一致，仅 typed 值格式与服务器 token 合法变化。每次 invocation 最多确认一个精确 label，且要求包含完整 prepared command+review 的原摘要；没有自动批准/自动替换 token。

execute 发送前 stage=execute_sending；timeout/HTTP 错误/异常均保留 execute_unknown。普通 invocation 不重发；`--recover LABEL` 仅同完整原 command/key/token 发送一次。普通 409/500/过期不能另造请求或自动再 preview。preview_unknown 不发第二个 token；需要实际服务器恢复合同，当前工具显式停止。错误仅固定 status/code，不打印 URL、响应正文、SQL、token、私有原文。保存成功先保存 Receipt，再进行后续 GET；GET 失败不会把已保存动作变成 unknown 或重发。

`--confirm` 与 `--recover` 互斥。普通失败/权限撤回不补用户、Grant、资格、窗口、库或来源。无作用域/Current/professional 依赖只暂停该段，原请求不变。

## B 消费的精确 checkpoint 字段

```text
schema_version='wave22-shared-build-v1'; marker; foundation_sha256; case_id; equipment_id
requests[label]={actor,original,body,stage,preview?,tier?,review_digest?}
receipts.build/demand/operational/assessment/approve-engineering/approve-manufacturing/start/actual/lot/samples/ready-A1/ready-A2 = actualReceipt
events.start/actual/lot={raw,line,reference}; ready_events={raw,lines,references}
operational_input=typedFactInput; operational_binding=exactBuild/config/scope
phase='two_A_readiness_facts_saved_no_handoff_or_test_run' # only if both ready Receipts retained
continuation={schema_version:'wave22-shared-build-continuation-v1',
  state:'readback_saved_requires_consumer_recheck',scope,purpose,maker_id,
  build:{id,revision,name,unit,planned_quantity,owner_id,visibility},
  configuration:{bom_id,bom_revision,engineering_id,engineering_revision,manufacturing_id,manufacturing_revision},
  execution_scope:{purpose,quantity,unit,site,window:{start,finish,original_timezone}},
  start:actualStartView,actual_configuration:actualActualView,lot:actualLotView,
  samples:[actualSampleView+{readiness:actualInspect.current_readiness,purpose_availability:'ready'}],
  required_source_read_set:completeUnion,readback_at,synthetic_only:true,
  test_qualification:null,professional_review:null,effectiveness:null,close:false}
```

continuation 只有 Root 真正运行 `readback` 且全部真实回读通过才写；本轮没有这些 actual 值。所有 reads 是每 phase 真正从 server DTO 拿完整集和新增精确出处的 union，冲突/超过 20 拒绝，不能切片。readback 对 current 限定开工资格的检查不移植为 Observer/Reviewer authority。

## 明确余项与来源预算

- Foundation 真实完成、Maker 各 op 精确 professional profile、当前质量/调查政策由 Root 统一配置；该工具不替 Maker 导入 professional facts，不采用 bootstrap 时点当资格。
- 受控 operational 本地 profile 须 Root 合并/重载，与其他 scope 同启，不覆盖 old key。窗口失效只接受实际既有服务错误，工具不延长固定窗口/proofTTL。
- 制造链若每个独立发生事件分别注册，当前最多新增 operational/start/actual/lot/ready 五份 Artifact，连同 Foundation 六份。后续全链 20 份上限须实际每 phase 核算；前期“19份预算”不能冒充本链测得事实。Root 可在首次注册时合并同次**已发生**完整记录、复用真正共同固定资料，不能预写未来、删除闭包或覆盖旧 Artifact。
- B 后续必须按两件真实不同 Sample 分支，原测和新复验不重复消费；真正测试资源/专业选择、原报告 scan/parse、Current paired owner、真实整改履行保持独立。没有效果/关闭/生产/人工 Exit 通过。

## 离线验证范围

独立 unittest 同目录，仅纯 helpers、精确 DTO/注册表和内存 transport 控制；Engine.connect/raw_connection、httpx.Client.request、target 全部主动封堵。替身仅覆盖 UNKNOWN/一次确认/保存优先，不冒充 server 资格或存储原子性。32项中首轮有1个既有 schema 循环导入启动错误，已按实际入口先从 PAYLOADS 注册表加载修复；保留失败日志。新低风险 Receipt 状态回读补一项后最终总数33，Ruff/format/AST 精确记录；不累计 26/32 中间版本、不称公共验证/实际执行。
