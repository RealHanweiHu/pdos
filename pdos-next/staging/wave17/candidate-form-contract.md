# Wave17 候选材料表单（暂存第六段）

只提供字段严格的 React 材料表单，尚未挂公共页面、API、Preview 或消费器。`CandidateForm` 不请求 HTTP、不造 Command／key／时钟、不授资格、不确认、不保存，不决定有效性或关闭。固定 Python 合同为候选 T1，确认 token 由未来共同 preview 返回，表单载荷中不含 token。

## 宿主输入与回调

`scope` 为当前实际 tenant/product/project/principal、logical Issue/CAPA、Current 精确行和版、原失败集合、既有受众与真实名称。`origin_issue` 只供追溯展示；提交 `expected_issue_revision` 始终取实际 Current，不能取原失败版本。缺 scope／固定身份非法时不显示材料。

`materials` 是三种宿主已核对的完整选项：

- `links`：实际固定 Link `id/v1`、标签、说明、受众。只允许 v1、不手输 UUID。
- `mappings`：既有 `FailurePairMapping` 全字段和只读业务标签、原值／工况／原 ISO 时钟／原时区说明。只能选整个对应，不能编辑值或配置；固定 Run 必须是实际不可变 `verification_run` 行，key=NULL。原失败须在固定失败集合内；测量／Projection 缺失仍为 NULL。
- `sources`：服务器返回的完整 `DefinitionReference`、真实标题与受众。只能选择整行引用，quote 不改写；不能猜 hash／locator。

三种选项拒重复，来源也拒重复，载荷最多 20 Links／10000 mappings／20 sources，每 mapping 的适用性出处也最多 20 条。最终完整来源读集闭包仍由服务器核验；这些表单数量约束不能代替服务器 ≤20 的完整读集上限。

`disabled` 缺省 true；只有宿主显式 false 才能填写。宿主负责真实 capability、当前版本／评估、privacy、pending、UNKNOWN 和恢复流程；`busy=true` 额外锁定。`allowProductVisibility` 缺省 false，只有宿主明确允许、既有范围为 product 且每个已选材料受众均为 product 才能选择 product。受众未知保守禁共享。该显示限制不是服务器授权。

`onChange(payload|null)` 通知当前完整无 token 材料或尚不完整；`onSubmit(payload)` 只交付完全相同的材料，不自动调用 preview／execute。原因必需 1..2000 字，原输入保留。Links／mappings／sources 可以空选，保存后的候选仍 indeterminate、三专业判断 NULL；不会补值或推论 pass。

输出精确字段为 `issue_id/expected_issue_revision/capa_id/remediation_link_refs/mappings/sources/reason/visibility`。不输出 anchor、basis、inspection、proof、hash、Current／qualification flag、Command 或 token。

## 范围变化与恢复边界

完整 scope 与完整 choices 用对象键稳定、数组语义原样的材料 key 定位局部表单。任何实际 Current、身份、原始对应、精确出处或选项内容变化都会重建空选择／空原因／private；通过 `onChange(null)` 使宿主知道原表单已失效。只改变对象键顺序不会换范围，实际 JSON 值、数组顺序和 ISO／timezone 字符串均不改写。

v2 将失效通知放在外层无条件 layout effect，合法材料变成 scope=NULL／无效固定身份／非法或重复 choices 时，即使字段子组件不再渲染，也会在客户端提交本次渲染时通知 `onChange(null)`，清除父层**当前可编辑草稿**。初始无效范围也通知一次；子层不再重复通知。外层实时 basis／locked 门闩拒绝旧渲染保留的填写或提交 callback，因此失效范围不能产出旧 payload。非数组等缺损 choices 明确视为无效，不因解析异常跳过清除路径。

v3 保留上述边界，将门闩更新从 render 移到无条件 layout effect：先提交实际 basis／locked，再通知 `onChange(null)`，事件处理只能读取提交后的门闩；渲染期间不读写 ref，丢弃的并发 render 不改已提交范围。effect 清理时只关闭事件门闩，不清原请求、不重复通知；卸载后保留的 callback 也不能产出材料。回调先解构并精确列入 effect 依赖，不压制 React lint 规则。旧 v2 的 ref render 写入错误及证据保留。

该局部重置不修改宿主已锁定的原 Command／key／payload／读集。UNKNOWN 时宿主必须保持 `disabled=true` 并只办理原请求恢复；表单不会自行解锁、清 pending、重预览或另造操作。保存回执优先、401/403 清敏感状态与精确过期恢复继续由已冻结父状态机负责。身份撤回时宿主应清 scope，表单即不渲染外部保留的材料／姓名。

宿主必须将 `onChange(null)` 解释为可编辑草稿失效，不能借此清除已经 prepared 的命令、pending UNKNOWN、原恢复 key 或已成功回执。本段没有这些对象，也不会调用父状态机的取消／恢复动作。

产品可见许可变化不会静默改写已选 product：载荷变为不可提交，用户需明确改选 private。未接通 typed choices 时明确显示暂无真实材料；不能以表单存在声称公开接口或专业资格已经接通。

## 静态范围

遵循 `web/AGENTS.md`，先读取 bundled Next 的 Server/Client Components 与 CSS 指南；只用已有 shadcn Button、Tailwind token、8px 圆角、Phosphor，与现亮暗主题同源。使用可换行／可收缩容器和至少 44px 点击区域，但未进行真实 320/390/1440 浏览器验收。

仅三份新文件；静态严格 React TypeScript 检查及源码哈希另存证据。未新增展示镜像测试，没有运行公共 web 构建、数据库、HTTP、浏览器或业务办理。
