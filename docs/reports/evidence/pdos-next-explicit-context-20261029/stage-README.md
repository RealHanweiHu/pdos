# 显式对象 / 版本 / 资料纠正 · 冻结暂存交付

本目录只暂存，不应用到正式树。交付以 `apply-manifest.json` 的 29 个文件为准（19 修改 + 10 新建）；不要复制整个 `pdos-next` 目录。公共 `agent_kernel/api.py` 没有修改，另交独立 `api-context-corrections.patch`。没有迁移、数据库操作、模型/embedding、服务启动、外发或 Git 写操作。

## 实际闭环

1. 已结束回答的原 `RunContinuation` → `AnswerFollowupActions` 内显示“换对象、版本或资料”。从实际 metadata options 查找、查看可读版本并选择；单条结果预选。按钮一次点击就是本人修改与下一轮请求，无额外批准。
2. 原 work-state POST 接受封闭 `action=correct_context` / `context_change`，服务器以原会话当前 Run、普通 Human RLS/原件扫描及依赖关系重新读取。只接受 type / actual source ID / expected revision；标题、hash、业务范围、分类由实际行确定。沿原 Run→advisory 锁顺序追加，原 request_key 同值恢复不重写。
3. “换为这个对象”固定实际选择的源版本；“只看所选版本”固定实际可读版本；“只用所选资料”形成严格固定集合。只有明确“当前有效”才解析实际头版本；对象存在时该次头版本也固定，后续不自动升级。全局 current-only 是当前性过滤，不能作为适用性或验证结论。
4. 后续请求携带可选 `context_revision`。服务器在原 continuation 的 Run/session 锁之后、实际工作状态 advisory 锁内做 CAS。保存 GET 后其它本人编辑导致 409；已受理原 key 先重放，不受后来的工作状态版本影响。旧请求不传此字段，None 不改变旧请求 digest。
5. 新 Run 的选择与 work-state digest 一起冻结；继承引用先按实际来源重核、再按固定条件筛选，之后才计算返回数/游标。实际检索 SQL 公共 authority CTE 在 direct/relations 的计数、分页前应用固定 type/id/revision/hash / focus / current 条件。内部 source-family 存在性探测保留品类根，防止其它可读项目的实际显式选择被当前项目提前剪掉。
6. 只清理新 Run 的被替换资料绑定；旧 Run/原引用/原回答保留。逐字约束继续用已有实际 goal 片段核验，Human 删除墓碑不复活。work-state 公共读取再次核权限；资料失效时不返回旧标题/ID，允许解除或重新选择。
7. 个人全局显式 Artifact 条件保存实际 scope/hash/revision/classification，沿普通个人读取权限；只读 `assistant.materials.read` 可消费这些固定 pin，仍二次核 RLS/内容/扫描。它们不写入个人 Run 的业务 `read_sources`，不变成业务目标绑定。模型自行附加未选择 ID 仍被拒绝。
8. UI 保留原 continuation / start journal，精确保留 CAS 与已有 deep 字段；状态保存后再 GET 最新实际状态，只有实际同一选择才开始下一轮。响应丢失使用原 Human key；原生下一轮响应丢失仍由既有 journal 恢复。

## 范围与真实边界

- Session 的 category/product/project/proposal lineage 合同不变。错项目/型号用既有范围导航进入对应会话；当前 UI 明确提示。显式讨论可选同品类内其它实际可读对象，不更换业务目标。个人跨品类固定资料也只读、不伪造业务绑定。
- Artifact 没有可读历史快照时旧版不能选；不会拿当前正文冒充旧版。Issue/Change/Knowledge 等通过现有固定来源版本目录返回可读版本。
- 原 `StartInput.sources` 中明确选择的资料才形成严格条件。verification / proposal 等服务器在 `effective.sources` 自动补入的绑定本身不形成严格条件。保留的严格条件仍约束资料读取，不会因为自动补来源而静默扩大；如之后动作需要集合外材料，须通过已有资料选择/解除条件表达新的本人选择。
- 历史回答仍保留历史内容；本层只控制新 Run 可重读/引用的资料。`is_current` 没有被当作当前适用性证明。
- 本层未做实际 PG、Temporal、生产构建或浏览器验收；这些由根统一执行。PG 草案 5 个实际 pytest case，尚未运行，不宣称通过。

## 精确基线 / 应用

- `base-sha256.json` 保存全部素材来源；真正应用必须只遍历 `apply-manifest.json.files`，核 `base_sha256` 后应用，再核 `sha256`。
- server 以 live verification merged 为底，仅按 manifest 叠 depth 两层、feedback 4 文件和 policy PG 补充。不可整目录覆盖上游 stage 的验证副本。
- work_state 基线 `69f1e253f40c333c1f6ca6acb4593eda720b4f4f5472cb5d0147ae6c18e46694`；assistant_scope 基线 `35ca2b3eb9b8dfa66e3c08711c77b96837e3e522ff3b87a7c71d911a6830f240`。
- web 底层是此前已交 corrections integration 的 702 输入。唯一后续重基线是 BFF route.ts，保留 root 当前 summaries 两处白名单；本文件 base `5491753de598a08ffe87f6c630b41a6961034b48020d12281b2707ee2c3ff416`。原 base 保留在 `base-before-bff-rebase.json`；未覆盖 Xiaopai/Personal/其新恢复接线。
- 临时树首次整目录叠副本时发现 assistant_scope 被旧验证副本覆盖，仅影响临时素材；已按 `tracked-overlay.json` 重建基线，原失败证据保留。最终 patch 在独立 scratch 以不可变 base snapshot 成功 `git apply --check` / apply，29 个输出 SHA 全匹配。
- 聚合交付 SHA（按排序 `sha256  path\n`）：`d1932e5365f0dd1a0cfe767bc1927161a0a33686cdbc2ec10635fa2503629eb2`。
- 全层 patch SHA：`c5ccf8ce68ee319cfd5038d6e1b6f0533acb9f1807aaae7028f915e46cf672a5`。
- manifest SHA：`6cf1508884505a26d3147c48300f5bbf02b6f364d052ca22ba0910a82bdea7fe`。

## 公共 API 独立接线

`api-hook.json` / `api-context-corrections.patch` 基于 depth API `666ee89418784cf833c28c7c04a91fd7c2bad7c39bce6ea0e03f6427a23ed0c2`，patch SHA `6472620feade21b0a6b5c8b9be8e8e8091f7b3d3c608524f6118df3e0464c6db`。根需手工并入当前带 checked_result/X3 的 API，只改三点：

```python
# StartInput
context_revision: int | None = Field(default=None, ge=1, strict=True)

# request digest，和现有可选字段同一 exclude 联集
| ({"context_revision"} if data.context_revision is None else set())

# 新建分支，在 conversation.prepare → verification.prepare_start → binding/create_run
# → depth/action versions → search_preferences.configure_start 之后、dispatch 之前，仍同 UOW
from .context_corrections import configure_start as configure_context_start
configure_context_start(s, ctx, row, data, effective, parent)
```

`configure_context_start` 必须同时拿原 `data` 和服务器 `effective`；不得把自动绑定当严格选择，也不得在 work_state 已冻结后再改条件而保留旧 digest。已受理原 key 的分支不重新配置。新 metadata options 已挂原 work-state router，无需新增注册。pure API 测试在本 stage 执行实际 API 独立 patch；根合入后检测实际 StartInput 字段直接执行真实 API，不依赖仓库根存在 stage patch 文件。

## 验证证据

- `evidence/backend-final-frozen.txt`：99 passed。4 个本层纯测试文件 29 项，加 work_state、反馈、排除、scope policy、deep integration、context schema/budget 受影响回归。旧 depth 测试仅补实际 advisory/最新 state 读所需 fake-session port，不改 depth 生产代码。
- `evidence/frontend-final-frozen.txt`：36 passed。实际 SSR/组件点击、保存→GET→下一轮、原 key 丢响应恢复、后来 clear 优先、原 journal CAS/deep 恢复、SourcePicker 与 BFF。
- `evidence/frontend-bff-rebased.txt`：3 passed，保留 root summaries delta 后的目标 BFF。
- `evidence/frontend-types-frozen.txt`：完整 `tsc --noEmit` 成功（使用现存类型/依赖，无新 build）。
- `evidence/frontend-lint-frozen.txt`、`evidence/backend-lint-frozen.txt`：目标 ESLint / Ruff 通过；交付 Python AST 解析通过。
- `evidence/delivery-verification.json`：29 文件 scratch 应用与输出 SHA 验证，独立 API patch 应用验证。

根的实际 PG 计划（只用根已核对的 TEST_DATABASE_URL，不回退 env）：

- `tests/agent_kernel/test_context_corrections_pg.py`：2 cases，真实 HTTP/本人 peer/跨租户、选择→SQL LIMIT 前过滤、原 key 恢复、保存 GET→另处编辑→CAS409、已受理重放、清空/legacy、原 Run 不改、逐字约束删除不复活、假 Artifact 旧版拒绝。
- `tests/agent_kernel/test_personal_context_pins_pg.py`：3 cases，复用 `security_work` 的离线真实上传/解析与 synthetic scanner 事实；本人跨两可读品类 pin 正常读取且无业务绑定；真实删除 read Grant 后拒绝；Artifact 内容/revision/hash 后续变化与 scanner 当前规则变化后拒绝，不隐式重扫。所有 ID/账号均测试夹具，无真实原件、外发或推理。
- 可再按根检查点对已有 work_state/continuation/verification/depth 实际 PG、Temporal 作组合验证。新阶段不得以这些草案代替实际结果。
