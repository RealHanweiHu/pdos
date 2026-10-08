# Wave15 B：固定双线变更持久适配检查点

本包只施工 `domain/change_execution/` 与 `tests/change_execution/`。38项本包纯检查、Ruff及编译通过；未运行数据库、HTTP、公共构建或浏览器。旧变更纯核、Wave14源码/测试、公共注册、迁移、角色和清单未由本包修改。本文件不声明业务集成验收或G3完成。

## 主线接入合同

- schemas：`ChangeCreatePayload`（旧RequestCreate四字段+visibility）、`ImpactComputePayload`（change_id/expected_change_revision/snapshot/hypotheses）、`GraphCaptureInput`（capture_key/change_id/expected_change_revision/reason）。只开放 `change.request.create`、`change.impact.compute`，仍为T0；本包仅允许具名当前human、有产品写权限及实际当前专业资格。AI资格与T2端口均未授予。
- models：`ChangeRequestVersion` / `change_request_versions`，`ChangeCurrent` / `change_request_currents`，`ChangeGraphCapture` / `change_graph_captures`。逻辑change_id与回执subject版本行id分开，impact随不可变Change聚合版本保存。主线须注册模型、单调DDL、RLS、不可变/生命周期门栓及Current首版1/沿连续前版推进守卫。
- service：共同 `validate/semantic/preview_view/apply/replay_subject/inputs`；`prepare_capture(s,ctx,product_id,GraphCaptureInput)`；`list_changes(s,ctx,product_id,issue_id=None,change_id=None)`。apply返回 `(ChangeRequestVersion,'change_request',visibility)`，不commit、不另写Receipt/Audit/Outbox，也不消费第二份证明。
- 配置：主线 `configure_store(engine,OriginalStore)`；固定Issue默认调用A的 `get_issue(s,ctx,pid,logical_id,revision=None,write=False)`，可由可信宿主 `configure_issue_loader(engine,callable)` 显式替换同签名端口。配置只提供依赖，不授范围/专业资格。无原件、可信存储或固定Issue端口均明确503。
- sources：人工新引用仅artifact `SourceRef{id,revision,kind:'artifact',position:'line:N;quote_sha256:<整行SHA256>'}`。服务端候选提供整行原文与引用；旧Failure/Run原位置由A/保存执行证明读取，未改旧定位格式。完整继承读集去重最多20份，超出明确422；全部有界原件字节I/O后重新核所有者、当前来源、安全epoch、专业事实及issuer/runtime。

## 返回结构

`inputs` 返回 operation/allowed/required_source_read_set/authority/review(before,after,effect,read_basis)，另含change_id/purpose/scope/source_status/blockers。create逻辑UUID由服务器绑定完整scope、当前人、受众与排序后的专用语义，换客户端key不产生另一请求。Product和Change CAS只在新写/preview办理，当前身份与来源在共同重放前办理。

捕获返回 `{capture,impact_payload,required_source_read_set}`。capture含id/revision/change_id/change_revision/graph/expires_at/created_at/current/source_status/owner_id/visibility/reason/readset/impact_payload。GraphSnapshot固定来源对象；capture专业operation与后续计算均为 `change.impact.compute`，不会引入影子操作。有效期最多10分钟并受资格期限约束；exact-key回读同图不能延长期限，载荷冲突、来源/资格/安全或运行配置变化拒绝。计算可追加有出处的假设，不因此忽略图原有来源epoch。

GET为 `{changes,captures,current_by_change,reference_options,source_options,capabilities,authority,unavailable_count,has_more}`。change每项含id（版本行）、change_id、revision、project_id、原ChangeRequest、current/source_status/readset/authority/capabilities/blockers。pointer为 `{version_id,revision}`。选择Issue时给真实固定Issue/CAPA引用与原文来源候选；CAPA Ref使用所属logicalIssue id、固定Issue聚合revision及真实CAPA UUID字符串key。读取能力不以“任一产品的资格”推出；来源不可见时隐藏整个派生记录。

## 已复用及准确缺口

直接调用旧 `ChangeControlHandler`、`compute_impact` 和固定DTO。私有 `_prepare` 仅集中用于物质before/after，纯核execute把Mutation交回本包保存；共同入口仍是唯一回执/事务所有者。未开放的政策、Order、selection、implementation、effectivity、verification、close端口均抛INTEGRATION_REQUIRED，绝不返回成功占位值。

实际图读取Issue失败→Build/Sample/Run固定引用、Definition/规格key、BOM及行/Part身份、EngineeringConfiguration、ProcessRevision及工序key/SOP字段、已登记Build与样件/Run关系。SOP节点引用固定制造版中真实SOP字段（不是独立正式SOP发布实体）。只读对象的实际关系可见；全八facet仍UNKNOWN。正式Tooling/Fixture/ControlPlan/PilotRun、ERP库存/WIP/生产切换、客户外发样件、培训与变更后证据适用性缺完整端口，不用已读子图宣称complete。250节点/每类所有者查询有界，超节点上限拒绝而不虚报完整。

首版要求**当前已分诊/CAPA的Issue版本**作为新写依据。固定旧Issue版可显示历史，但A目前标not_evaluated_historical、缺固定版失败再核接口；Issue后来续版后原Change新计算明确RECHECK_REQUIRED，不能把历史“已读”改成current。旧配置仍按精确合法固定版本读取，不擅取latest。

待主线验收：真实共同T0/专业映射、三表约束与指针/生命周期保护、固定失败原件桥、创建跨key去重、当前权限先重放、Change CAS、捕获key冲突/期限/ABA、private受众、末端Outbox故障全组回滚、双线已知路径与UNKNOWN、真实页面。当前38纯检查不替代这些PG/HTTP出口，更不证明实际整改、生效、发布、生产或人工Exit。
