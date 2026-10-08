# Wave17 暂存 React 办理视图 v1

本包只新增 `ui-view.tsx` 与本文，使用已冻结的四文件 UI DTO/状态包。导出 `CapaEffectivenessView`；未接公共页面、HTTP、BFF、业务来源、数据库或资格端口。可阅读与展示不等于实际办理已启用。本次只验证所属 TypeScript/React 类型；实际页面、两主题和手机图形验收由主线以后统一挂载执行。

## 宿主接法

组件是 client component，必须由真实客户端宿主传入状态与回调；不得从 Server Component 跨边界传递函数。复用现有 `Button`、Tailwind、panel、Phosphor 和双主题变量，不新增 UI 库、CSS 或公共配置。

| prop | 要求 |
|---|---|
| `state: UiState` | 宿主使用冻结状态函数接收经过实际适配的 DTO；选择、权限、读水位和原请求都保留在此状态中。 |
| `busy: boolean` | 宿主实际在途办理状态，防止同一回调重复触发。不得只依据 HTTP 到期自行清除原请求。 |
| `callbacks` | 显式选择、读取、准备、确认、原请求恢复、重新预览和提交前取消；组件不生成载荷或自动调用。 |
| `issueOptions` | 当前实际可读的固定版本和真实名称。没有列表时保留明确空选，不按日期或 Current 默选。 |
| `labels` | 仅宿主已读名称。记录键 `kind:id:revision`；人员键 `principal:id` 不虚构人员 revision。名称不影响任何资格门闩。 |
| `operationForms` | 每操作的真实 typed 表单槽与 `complete`。缺槽、空内容或完整选择未完成，明确“办理材料尚未接通”且禁预览。槽本身不构造命令、读集或资格。 |
| `renderPreview(review, operation)` | 只接收到 before/after/effect 与操作名，不能获得 token 或完整命令。宿主必须展示该操作完整业务差异和来源，返回实际 `complete`；缺内容禁确认。 |
| `detailSlots` | 原失败对应、实际观察、专业复核的只读业务明细。缺少时明确完整映射/记录尚未接通，摘要不能代替这些事实。 |

宿主传入的槽必须由同一次明确 scope/Issue/anchor 和预览生成，不能携带上一个身份或版本的内容，也不能放原始命令、token、任意 JSON 编辑器或自授资格入口。只读槽不得含写入控制。表单完整性仅表示材料可进入核对；服务器 `allowed`、职责/资格与冻结 `canPrepare` 仍独立必需。

## 办理顺序与回调责任

五操作沿冻结名分别呈现候选 T1、观察 T1、具名复核 T2、有效性 T2、独立关闭 T2。Rule publication 只有受控宿主返回的只读记录，不提供发布、导入或自授按钮。候选固定三项 NULL、indeterminate，不提供肯定勾选。unknown/not_applicable/ineffective 区分显示。

`onPrepare(operation)` 由宿主收集真实 typed 表单、精确固定选择和完整读集，调用原状态包 begin/inputs/preview；缺实际 API/端口则表单不接通，不用空载荷走正例。预览返回后只有显式 `onConfirm()` 进入冻结 confirm 和实际 execute；T2 文案明确“本人具名批准”，两次 T2 各自完整办理，不能借上一回执自动关闭。

`onRestore()` 只恢复 pending 原 mode/command/key/payload/readset，不能新建标识或重新生成事件。`onRepreview()` 仅在状态已经是 expired_preview 时显示，保持原材料并要求再次人工确认；组件不会因本地时间或普通错误自行把 execute UNKNOWN 变成该状态。新五操作的过期恢复 transport 尚未冻结时，状态包默认不解锁；旧 Wave16 code 不能当新协议复用。

`onCancel()` 仅在尚未 execute 时显示。回调由宿主处理实际异常和状态转移，不从 rejected Promise 猜业务是否保存。每次确认实际提交完整服务端 prepared 命令；组件不展示、复制、修改或序列化该命令。

## 当前、历史、隐私与时间

当前办理门闩使用 `state.model` 和冻结 `canPrepare`，不从 labels、槽、Product write 或表单 checkbox 产生能力。历史与 Current 分开显示；历史当前资格未评估，不把 NULL/missing 当肯定。late Link 的 planned 不变 performed：前者明确计划/历史且未证明实际复验，后者仍要求核对完整事实。旧私有调查不能因 peer grant 升成独立办理。

execute UNKNOWN 时固定版本选择、刷新与全部表单/新动作锁定，只保留“按原请求恢复”。已保存回执优先于随后读取失败：显示已保存、只允许读取当前事实，不重发。401/403 由冻结状态包立即清敏感；组件在 context 被清除后提前返回，仅最小非敏感结果提示，不渲染外部 labels、选项、槽、预览或历史明细。宿主须销毁旧 scope/caller 的生命周期，不能把旧异步回调投递给新状态。

观察区间、发生时间和原 IANA 时区逐字显示，保留 ISO offset 与完整小数秒。不 Date.toISOString、不补 now、不用保存时间替代发生时间。预览的 `server_on_save` 解释为“保存时服务器记录的时点尚未生成”，不当已经发生的观察钟。真实精确事件、时序与来源内容仍由服务器核。

业务名称缺失时显示明确未知；实际 immutable ref/人员标识置于折叠对账细节，主流程不铺开 UUID、内部代码、SQL 或存储信息。来源/current_evaluation/缺项从 DTO 原投影读取，不因缺项数组为空宣称全部齐备或合格。

## 尚待主线冻结与实际验收

当前 DTO 不含逐失败与复验对应、逐项观察原记录、完整专业复核业务明细或五操作具体表单 schema。组件保留窄槽，缺材料禁办；本文没有新增公共字段或 RPC，也不把槽当新 API 授权。Root 后续需冻结真实 payload、读集生成、preview 完整业务投影、Receipt family 和对应 transport 后挂载。

本次 strict TypeScript/React/noUnused 检查仅包含新组件及必要依赖，noEmit，配置在临时目录。未重跑既有 26 状态纯检查，未新增镜像组件测试，未跑公共构建/浏览器/HTTP/PG；没有实际有效性、关闭、真实专业资格或生产放行的完成声明。
