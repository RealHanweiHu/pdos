# Wave16 页面前置准备工具（离线交付，未执行）

唯一新增源码：`pdos-next/tools/wave16_demo_setup.py`。本交付只做源码、类型接口与静态边界核对，没有连接数据库、HTTP、浏览器或执行公共测试。Wave15 v4 的 303 个冻结文件逐文件摘要仍匹配；本工具不属于 Wave15 联验候选。

## 执行门禁与独立状态

主线稍后运行时必须显式提供 `--marker UUID --expected-head next_XXXX --phase PHASE`。每个数据库边界重新读受控运行状态，先核对本任务标记、容器身份、三个 URL 均为本地 `62513/pdos_test`，再调用既有 `verified(read_state())` 的实际数据库标记核对。只读管理员连接用于真实 Alembic head；业务写入使用租户 app Session。工具不接受环境变量回退或 URL 参数。

只读既存、600 权限、当前用户持有的 `pdos-next/.local/wave15-seed.json`，只选取实际标记、tenant/product/project/actor、logical Issue/CAPA/action 身份；不复制登录 token，不实例化旧 `Demo`。当前 Issue 必须可见、未归并、无待重核、已有 CAPA，原失败必须全为 synthetic，且无有效性或关闭结论。措施必须唯一属于当前具名执行人；seed 已记措施或 `--action UUID` 不能互相冲突。当前 Issue/措施摘要核对只用于准备材料，不宣称原失败、根因或专业结论已通过新的审批。

独立恢复记录为 `pdos-next/.local/wave16-seed.json`，独立并发文件锁为 `.local/wave16-setup.lock`。以固定 setup UUID、命令 UUID、幂等键与原始 payload 持久化后才办理实际出处登记或可信签发；commit 后检查点未保存可重发同一命令。已保存材料异值、scope/措施变化、有效期变更均拒绝，不能隐式续期或换新键。文件为受控原子写入、600 权限，拒绝 symlink、非普通文件、非当前用户、hardlink、多于 8 MiB 的旧私有记录、重复 JSON 键和非有限 JSON。旧 seed、旧质量 profile 及原件字节不修改。

写入前要求三操作已经出现在共同 PAYLOADS/handler、专业矩阵与正确分级中：

| 操作 | 必须已接入的层级 | 本工具是否执行 |
| --- | --- | --- |
| `quality.issue.root_cause.decide` | T2，允许 quality 专业角色 | 否，由主线页面具名决定 |
| `quality.capa.actions.complete` | T1，允许 quality 专业角色 | 否，由主线页面本人确认 |
| `quality.capa.followup.link` | T1，允许 quality 专业角色 | 否，由主线页面确认真实输出 |

若公共分级/专业矩阵未接，返回 `FOLLOWUP_PUBLIC_MATRIX_INTEGRATION_REQUIRED`。本工具不会修改政策、注册操作、自授正式资格、启用 AI 或代办 T1/T2。

## phase 与实际材料

| phase | 前置与结果 |
| --- | --- |
| `authority` | Common `evidence.artifact.register` 登记三行具名合成职责原文，实际 Artifact/Receipt 整行引用；可信 `import_professional_fact` 追加每操作 duty/qualification 各一版，共六个新外部系列，保留全部旧系列。仅经核验本地目标启用既有 server-held `local-synthetic-authority/v1` issuer。截止时间首次固定，默认签发后两日或明确 `--valid-until`；重发不能续期。 |
| `root-source` | 必须明确 `--root-text`，登记单行 native 合成调查提议，原文标注“待具名T2决定；非有效性/关闭结论”。只保存出处与原文本，无根因批准。 |
| `completion-source` | 必须明确 `--occurred-at`、`--timezone`、`--completion-text`。发生时间须 aware、已实际观察且非未来；原输入 ISO 字符串与规范 UTC 分开保存。IANA 时区按现有 EventTime 合同核对。登记实际九字段 JSON 行，经真实 Artifact/Receipt/整行位置核对，再用既有 `CompletionFact`/`Completion`/`verify_completion_line` 验证字段一致。不存在从当前时钟、未来计划或仪器报告补造完成事件。 |
| `classification-profile` | 必须首次明确 `--valid-until`，登记十二字段 native 调查分类原文；`action_sha256` 精确取固定 CapaAction 的 `model_dump(mode='json', exclude={'completion'})`。生成严格 `CompletionProfile`。只允许 investigation/synthetic，不授 formal-change 或有效性资格。 |
| `owner-options` | 只经既有公开适配器实际 owner/Receipt/来源读取既有 OutputRef；保存候选但 `candidate_verified=false`。缺少真实失败/owner/runtime 端口明确停止，不用 UUID/标签或空子图伪造候选。此可选 phase 的深层运行配置仍由主线接入；本工具不补乐观 callback。 |
| `status` | 读取准备记录并显示有界计数，不执行业务写入；文件锁元数据可正常使用。显示“saved”仅指已保存准备记录，不表示当前执行许可。 |

九字段 CompletionFact：`issue_id, capa_id, action_id, executor_id, operation, occurred_at, original_timezone, purpose, text`。

十二字段 ClassificationFact：`tenant_id, product_id, project_id, issue_id, capa_id, action_id, executor_id, purpose, action_sha256, classification, nature, valid_until`。

所有新出处都是本地合成、服务器原生登记的不可变文本，使用真实 Artifact 注册回执核对，并保留 `source_kind=registered_native_text`。不能冒充仪器报告、UploadedOriginal 或真实生产事实。三项签发共用一份三行原文；来源读集、专业资格、政策与真实回链仍由正式领域入口当前核对，不截断已有来源以绕过 20 项上限。

## 分类 profile 与主线页面衔接

唯一待启用路径为 `pdos-next/.local/quality-followup-synthetic-profile.json`；seed 同时保存精确 profile 与 canonical SHA256。已有异值文件在新增分类登记前即拒绝，不覆盖、不生成第二份启用配置。保存 profile 前再次核对具体源码的 `CompletionProfile` DTO；主线随后显式启动注入该文件，工具不重启服务、不调用 configure_integration、不把写文件当已经生效。

`wave16-seed.materials.observed_completion.raw` 保留明确观察的原发生时间与文本，`completion_for_ui` 保留实际登记来源生成的 DTO。页面必须重新读取当前 Issue 版本、完整 readset、当前权限与专业事实后进行 preview/决定；不能把准备时 Issue revision 当最新、不能把 setup 结果当确认 proof。

主线填写真实已观察时钟及自己的标记/head 后，调用模式如下（占位值不可直接执行）：

```text
pdos-next/server/.venv/bin/python pdos-next/tools/wave16_demo_setup.py \
  --marker <本任务已核对UUID> --expected-head <主线当前next_XXXX> --phase authority

... --phase root-source --root-text '<明确合成调查提议>'

... --phase completion-source --occurred-at '<已观察aware ISO>' \
  --timezone '<IANA时区>' --completion-text '<本人已完成的合成调查事实>'

... --phase classification-profile --valid-until '<明确aware截止时间>'
```

命令输出只含 phase/计数/准备标志/安全错误码；不输出 token、私有原文、数据库 URL 或异常 SQL。任何失败保留已提交的实际登记及恢复记录，不代办补审批。

## 离线检查范围

该新文件 Ruff check/format、AST/内存 compile、惰性模块加载通过；离线检查九/十二字段 DTO、可信导入/配置函数签名匹配，并核对 naive/multiline/隐式 trim 输入被拒绝。没有运行 CLI main、Docker、数据库、HTTP、pytest 或公共验证。实际资料登记、六事实签发、profile 源核对、页面预览/确认和恢复演练均待主线统一执行。
