# Wave22：共享三人专业/政策受控导入工具（暂存交付）

仅隔离实现与静态检查，未读取真实私有 checkpoint/profile、未运行工具、未连接数据库/HTTP、未重启服务。Root 负责应用、真实目标核验、宿主导入、API profile 安装与三人当前专业读回。本交付不宣称生产资格、独立性成立、任何 T2 决定或未来业务实绩。

## 文件与真实入口

暂存工具 `pdos-next/.local/wave22-authority-staged/wave22_shared_authority.py`；Root 可原字节迁入 `pdos-next/tools/wave22_shared_authority.py`。两个布局准确定位 pdos-next；导入模块无环境读取/连接/配置，CLI 执行才发生边界。只接受以下 Root 显式执行方式：

```text
PYTHONPATH=server:tools server/.venv/bin/python tools/wave22_shared_authority.py prepare --marker <actual-marker>
PYTHONPATH=server:tools server/.venv/bin/python tools/wave22_shared_authority.py import --marker <actual-marker>
```

两个可选路径参数为 `--professional-profiles`、`--quality-profiles`。默认明确旧列表 `.local/professional-synthetic-profiles.json`、`.local/quality-synthetic-profiles.json`；非空 JSON list、完整精确 fields、旧顺序/内容原样保留，新独立 scope/key append，最终≤20。拒绝旧 key 扩围、重复 key/scope、非法/额外字段、隐式默认注册。并不安装或修改这两个旧文件。

## Foundation 准入：结构与实际保存分别核

只消费当前用户 owned regular 0600、非 symlink 的 `.local/wave21-shared-case.json`，schema `wave21-shared-foundation-v1`，phase 必须 `foundation_saved_not_build_started`。缺失/未完工在环境验证前拒绝，不用 Root 消息或传入 UUID 替代真实保存证据。

结构核：Product/Project/tenant/marker/purpose/product 受众、三个不同 human ID、七份实际 Receipt operation/family/Maker actor/requester/id/result/严格整数 subject_revision；完整 Foundation readset 对照实际 native Receipt revision；三人读回各精确 `{shared_objects:6,stored_content_hash,raw_text_sha256,professional_qualification:null}`。保存摘要与原 UTF-8 摘要分列，不假定两算法；工具不复制 login_token/requests。保留 Definition 实际 revision（允许 v4），新 source 引用也只取实际 Receipt revision，不硬编码 1。

每个真实 UOW 重新核 Product/Project exact tenant/product/owner/purpose/visibility/status、七原 Receipt 全字段、三名 active human/同 scope 当前 can_write Grant/真实期限、三人分别 source_for 与 native registration source_basis/当前 ACL；共享 native owner Maker、original_id=None、服务 digest/content_hash 与原 UTF-8 SHA 均精确相等。Product lock、scope/来源失败不补权限、不借作者 Context给消费者。实际 `verified(read_state())` 验62513/显式 marker 与 preview_tenant；不回退 .env，不打印配置/URL/登录材料。

## 精确职责组与期限

| 组 | 真实 subject / role | Operations 数 | 固定范围 |
|---|---|---:|---|
| maker-engineering | Maker / engineering | 9 | Build工程批准；Issue create/merge/triage/containment；CAPA draft/本人完成/回链/candidate |
| maker-manufacturing | Maker / manufacturing | 4 | Build制造批准/Start、Sample readiness、Offer |
| maker-quality | Maker / quality | 2 | 根因、host-only Rule import |
| observer-quality-front | Observer / quality | 7 | Request/计划与实际方法/Accept、Run Plan/Promise/Start |
| observer-quality-results | Observer / quality | 5 | 原值import/compute、Run review/disposition、Observation |
| independent-reviewer-quality | IndependentReviewer / quality | 1 | 仅 quality.capa.verification.review |

各组各一份 duty、一份 qualification，共12份真实 FactInput；actual OPERATION_ROLES 与实际 DTO检查，不发明 test role，不将 Root 字符串或 payload 当专业授权。资格仅标 nature=synthetic，由新独立 opaque issuer 实际验证。Maker 签发不等于代行 Observer/Reviewer 的实际业务/T2。Reviewer 不参与测试/报告/根因/完成/Observation；最终独立由真实 owner 再判。

publication 首次真实 UTC issued_at（保留微秒），固定 valid_from=issued_at−1min，valid_until=min(三人真实 Grant 截止、Foundation bootstrap 截止)。重新 invocation 不续期、改钟或修改已登记事实。目录许可仅针对明确未来可办理 operation，并非未来业务已发生事实。实际角色组和操作完整列表见工具 `GROUPS`。

## 新的完整原文与政策

一次真实 `evidence.artifact.register` 保存全新 product 共享 native Artifact，共14行：12份完整专业出版 JSON；第13行严格既有 Policy publication 八键原文；第14行完整 tenant/product/project/purpose/issuer/nature/publisher 及第13行 hash 绑定。每行全 quote≤4000，拒重复 JSON键/NaN/Infinity；后续来源都为原行精确 DefinitionReference，不能用关键词材料代替 FactInput，也不把 scope 加进旧 Policy 八键算法令其失配。

风险保持 high、independent_verification=True；一份 PolicyInput引用两行完整来源。Scope/new issuer key 为 `wave22-professional-{case_id}` / `wave22-quality-{case_id}`，version v1；不复用旧 private policy。专业、政策合用一份新 Artifact 版本只增加一个 SourceRead，后续所有真实闭包仍须独立≤20，不能凭这个预算宣称全链通过。

## Prepare / import / 恢复边界

`prepare` 先验证实际 Foundation与明确旧 lists，捕获固定出版材料与真实 Product expected_revision。native Command UUID/key固定并先保存；后续沿原 Command/key/revision/payload，不重建 Product/Project、无自动修复。新 source receipt 保存后输出状态 `publication_saved_profiles_reload_required`；只表示出版已登记，实际专业导入数为0，不声称 current资格。Root 可先同工具 host-import 后再统一安装列表/reload；工具不代改 API。

`import` 在工具独立 engine 上以真实 configure_local_synthetic_profiles / quality.configure_local_profiles构造明确 finite opaque issuers；新 issuer 必须 synthetic且 exact新key。在一个 tenant_session/UOW 中，先重核 Foundation、真实新 sourceReceipt、三人 ACL/原文字节，然后逐12个 import_professional_fact + 一个 import_quality_policy_fact；实际 wrapper 单一 Receipt/Audit/Outbox/RequestKey、当前 issuer与来源重核/幂等，不另建 proof/Receipt/commit。host-only政策与专业操作均不注册 public PAYLOADS。所有失败回滚本 UOW；前段原生出版保持实际已保存历史。

跨重试全部 payload/issued_at/valid_until/uuid5 command/key原样；wrapper 重放仍核 current issuer/source，不用 checkpoint 的已有 receipt 直接跳过真实验证。commit后私有文件写失败可能出现“实际已保存、checkpoint未齐”的恢复情况；下一次同 key再次查询真实 wrapper Receipt，不换 key、不制造第二事实。工具自行只报告安全 error code/异常类型；故障响应全文、SQL、URL/token不打印。

私有新输出均 owned0600且原子文件替换：`.local/wave22-shared-authority.json`、`.local/wave22-professional-synthetic-profiles.json`、`.local/wave22-quality-synthetic-profiles.json`。后两者是完整旧列表+唯一新 entry，Root仅在工具 exit0后安装明确列表并重启实际 API。不会覆盖 `.local/wave21-shared-case.json`、原 lists、旧 preview_token/principal、任何旧 private 产品/事实/资产。

import成功状态 `synthetic_facts_saved_root_reload_required`；Root还须实际专业/政策当前读回，才能推进业务。工具未创建 Build/Sample/Request/Run/Issue、未登记未来实物/完成/观察、未发独立Review/有效性/关闭结论。

## 自有检查范围与未验证部分

保留36项初版原始日志；最终42项 `--noconftest` 纯检查覆盖实际 FactInput/PolicyInput/OPERATION_ROLES、实际 Policy原文parser（来源/ACL为明确替身）、实际新多scope bootstrap（marker为明确替身）、完整 Foundation字段/非final/bool/旧readback拒绝、实际旧名单identity保留、重复/容量/期限/私有文件/原材料不续钟等。Ruff、format、in-memory AST与冷导入只检查两个暂存文件。

纯例中的 Receipt、原 Foundation、人/源读回是结构材料替身；并未证明真实目标/当前 ACL/原件/Receipt持久性/专业事实已导入。没有公共pytest/collection、DB/HTTP/浏览器/服务重启、生产资格、真实业务办理或完整三人闭环通过声明。Root应用与实际验证为下一实际执行边界。
