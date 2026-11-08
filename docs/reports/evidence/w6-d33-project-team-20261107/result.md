# W6 ① D33 项目成员、租户角色目录和迁移（2026-11-07）

分支 `pdos-next/design-v1.1`（worktree `claude/intelligent-herschel-74d5dc`），迁移 revision **`s0_0855`**（down `s0_0854`）。依据：确认稿 P34 第 1 项、P55、P56、P60 第 4 项；用户 2026-11-07 对两处空白的拍板（经设计会话转达，见下）；设计稿 `2026-11-01-project-team-cockpit-mentions-design.md` §4.1–§4.3、§11 第 1 项；v1.1 附录 A 表下 P34 登记的 `project.member.set`（T1，仅项目负责人）、`project.role_catalog.publish`（T1，仅租户管理员）。

## 做了什么

| 部分 | 内容 |
|---|---|
| 数据 | 五张表：`project_role_catalog_versions`（租户级、只追加、版本号连续）、`project_team_changes`（团队修订号与幂等请求，只追加）、`project_members`（一人一段任期：加入时间、添加人、离开时间、移出人、离开时角色）、`project_member_roles`（当前角色；部分唯一索引保证每个角色最多一名主责人）、`project_member_audiences`（成员依赖的型号/立项定义/变体受众，及是否由本次加入添加）。不带品类列，范围经项目行自身的行级策略取得 |
| 守卫 | 只有在世具名人员、且当时持有本品类有效授权的人能加入（小Pai 等智能体不能）；负责人始终在团队中；离开前须先解除角色；历史只追加；提交时检查“项目受众 = 当前成员”（数据库约束触发器，受众行或成员行任一不一致即回滚）；只有成员已结束时负责人才能撤回项目受众行（替换 `object_audiences` 的 `m3_share_delete_only` 策略，提案部分原样保留） |
| 拍板 1：移出（P56 临时口径） | 私有项目中，移出时此人有未交接事项（本人受派或承接未完的任务、作出且任务未完成的承诺、本人负责的未关闭外部等待）的，成员资格和角色立即结束，项目受众保留并标“待交接”；交接完成后由负责人“完成移出”，此时才撤受众。没有未交接事项的立即移出。交接期可见范围比 P56“其他内容立即不可见”宽，记为余项 |
| 拍板 2：型号与定义受众 | 私有项目加成员时，同一事务把此人加入本项目型号、立项定义 v1（有变体时含变体）的受众，前提是这些对象由项目负责人本人所有；否则不代加，成员行标“需要型号资料可见，请联系 某某”。受众记下来源：随本项目加上的，在完全移出时一起撤回，若此人另一当前成员资格仍依赖它则保留并转由那一方负责；原本就有的或别处授予的（如 G0 授予）保留。定义来源里的私有原件不自动扩大 |
| 权限 | 五表对 `pdos_agent` 零权限；读写都要求具名本人（actor = requester）；写入须为项目负责人且有品类写权限，或正在执行的 G0 决定本身 |
| 角色目录 | 未发布时为设计稿 §4.1 的 12 个缺省角色（版本 0，可编辑初始值）；租户管理员发布新版本；被当前成员担任的角色不能删除，只能停用；停用后不能再分派，已有担任不变（P60 第 4 项）。正式内容待 D66 |
| G0（P55） | G0 物化时同一事务把加入项目受众的人登记为成员，角色留空；G0 决定预览列出“批准后登记为项目团队”，回执 `project_member_ids` 列出成员 |
| 回填 | 迁移把已有项目的项目受众回填为成员（来源 `backfill`，添加人记为当次 G0 决定人）；降级只允许在没有回填以外的记录时进行 |
| 接口 | `GET/POST /v1/categories/{c}/products/{p}/projects/{id}/team`（动作 add / set_roles / remove / complete；整张变更一次请求、一次确认；幂等键、修订号冲突、主责可在同一请求内转移）；`GET/POST /v1/role-catalog`（租户级） |
| 前端 | 项目“更多 → 团队”：成员表（角色、主责、加入、品类授权、需要型号资料可见）、空缺角色与未定主责、添加成员（无授权者显示“需要品类授权”不可选）、角色抽屉（多选、设为主责并提示从谁转来、移出前按有无未交接事项说明后果）、已离开成员（待交接、未交接计数、完成移出） |
| 合同 | `auxiliary-operations.json` 登记 `project.member.set`（T1）、`project.team.read`（READ）、`project.role_catalog.publish`（T1）、`project.role_catalog.read`（READ）；`/v1/role-catalog` 纳入未登记写入检查。v1.1 附录 A 表下已有前两项的冻结登记，未改冻结稿 |

## 验证

| 检查 | 结果 |
|---|---|
| 迁移 | 独立 `pdos_test` 上 `upgrade head`、`downgrade -1`、`upgrade head` 通过；回填后已有项目受众与成员一致 |
| 新增后端 | `tests/projects/team_pg/test_project_team.py` 10 例全过。拍板部分：加入私有项目即可见型号与立项定义并记来源、完全移出后三者都不可见、G0 授予的型号受众保留；有未交接事项时移出保留可见、未交接时“完成移出”422、交接后完成移出即不可见、重复完成 409；交接期重新加入时受众转由新成员资格负责；项目负责人不是型号所有人时不代加并标出所有人；真实分派任务计入待交接（任务 1）。原有部分：G0 登记团队与回执、负责人增删改、幂等重放、过期修订号 409、双主责 422、主责转移、非负责人 403、移出即不可见并保留离开记录、负责人不能移出、再加入开新任期；无授权 403“需要品类授权”、小Pai 422、授权过期后显示需要授权且不能看见；品类共享项目增删成员不改变可见；角色目录版本 0、非管理员 403、发布、删除被担任角色 409、停用后保留担任且不能新分派；四表强制 RLS、`pdos_agent` 无权限、智能体会话读不到、数据库拒绝智能体成员、受众与成员不一致在提交时回滚、历史只追加 |
| 受影响后端 | 见下方“受影响测试” |
| 表目录与漂移 | `test_m3_lifecycle_catalog.py`、`test_combined_registries.py` 通过；ORM 与迁移比对中新表无差异。比对检查本身仍失败 7 项，全是基点已有的（钉钉摘要索引、6 个向量索引），与本项无关 |
| 合同 | `tools/export_contracts.py` 后 `tools/validate_contracts.py` 通过 |
| 前端 | `pnpm typecheck` 通过；改动文件 eslint 无错误；`route.test.ts` 新增团队/角色目录路由用例通过；`src/lib/project-team.test.mjs` 3 例通过 |
| 浏览器 | 两个合成租户（真实 G0 链路），负责人身份。待交接：G0 待决项负责人陈舟有一条真实分派任务，移出前提示“还有未交接事项（任务 1）”`remove-with-open-task-dark.jpg`，移出后列为待交接、完成移出不可用 `handover-light.png`、`handover-dark.png`，重新载入后 console 无错误。其他：亮色成员表 `team-light.png`；添加成员中无授权者 `add-member-needs-grant.jpg`；主责从陈舟转给许晴 `role-editor-lead-move.png`；暗色移出后已离开列表 `team-dark-departed.png`、暗色抽屉 `role-editor-dark.jpg`；品类共享项目说明与 375px 宽度已目测 |

## 受影响测试

preproject、projects、my_work 收件箱与关注、command_catalog 等 1796 例的串行回归在提交时尚未跑完。已出现的失败集中在 `test_evidence_commands_pg`、`test_evidence_guards_pg`、`test_material_proofs_pg`（智能体登记工具摘要校验“实际登记工具或技能允许操作已变化”）和 `test_m3_fixed_consumption`（`SimpleNamespace` 假项目缺 `revision`），与 D27 记录的既有失败同类，未触及团队代码路径；但尚未逐项与 D27 两份既有失败清单比对，这一步是余项。
