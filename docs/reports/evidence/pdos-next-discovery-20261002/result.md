# Discovery 独立首版交付

2026-10-02。范围：G1.1 无项目研究与 OEM 多证据导入到可交给产品定义所有者的受控候选。仅写授权的 discovery 领域、DTO、纯检查、独立组件和本证据目录；未改公共注册、迁移、BFF、页面或唯一清单。

## 可调用能力

- `Discovery.start/ingest/inspect`：服务器绑定研究 scope、用途、租户、具名人员与受众；研究不依赖 Product/Project。来源包和观察不可静默覆盖；按内容去重，保留未知、原文、精确位置、原单位/允差/方法/条件/适用范围。输入和持久聚合采用封闭 DTO。
- `Discovery.preview/handoff`：按稳定参数标识比较并列值、单位、条件、方法及适用范围；逐组具名选择、保留冲突或部分导入。映射已有 `DefinitionDraftPayload`，固定真实 Product/父版、来源读集、观察核验和选择依据；确认时重新计算并拒绝变化。仅产品领域拥有 DefinitionRevision/Spec 写入。
- `PinnedSources`：对服务器读取的当前快照重核租户、研究/Product 绑定、ACL/受众、有效版本、正文哈希、精确原文行及不可变原件版本/映射。窄范围结构化 JSON 对全部规格字段和原文字串逐项比较；同名重复字段、普通原文、翻译或字段不对应均保持待核对。引用与哈希不会自动证明原值或授予成熟度。
- 五个可接入组件：研究保存、来源包/观察阅读、授权来源人工录入、逐组选择、固定定义候选阅读。采用现有 Button、主题 tokens 和 Phosphor；十进制通过字符串保存精度，缺项留空。`onPreview` 交给主线现有统一确认组件；本包没有第二套确认或回执入口。未接 port 明确禁用，失败保留输入。

AI 抽取、翻译、人工观察、服务器重核的已接受需求与正式规格分开；本包不允许 AI 写入、不授予 T0 资格、不发布规格、不创建项目、不表示客户批准。

## 固定候选与检查

17 个包内源码/DTO/测试/组件配置文件，候选 SHA-256：`7ada664c5e900d0f85d919770a915c8764ee657a934366bd4a2acc6369b69b57`。文件摘要见 [candidate.json](candidate.json) 和 [candidate.sha256](candidate.sha256)。消费的 15 个设计/公共接口文件初读与交付前摘要一致，见 [初读](consumed-interfaces.initial.json) 与 [复核](consumed-interfaces.final.json)。

| 检查 | 结果 | 原始输出 |
|---|---|---|
| 显式合成输入、纯 Python 领域检查 | 63 passed | [pytest.txt](pytest.txt) |
| 独立组件 SSR、实际表单/选择回调、错误与禁用行为 | 11 passed | [components.txt](components.txt) |
| 包内 Ruff，禁缓存 | 通过 | [ruff.txt](ruff.txt) |
| 局部 TypeScript，nonincremental/noEmit | 通过，退出码 0 | [typescript.txt](typescript.txt) |
| 局部 ESLint | 通过，退出码 0 | [eslint.txt](eslint.txt) |

精确命令和退出码见 [checks.json](checks.json)。Pytest 禁插件自动加载、bytecode 与缓存，`--confcutdir` 限于本包。组件转译只在内存。首轮 ESLint 对测试用 hook dispatcher 报规则错误，已仅在测试 shim 限定范围说明规则豁免并重验；原输出保留于 [eslint.initial.txt](eslint.initial.txt)。领域导入先初始化共同 StrictModel，避免现有共同 DTO 的循环初始化；未修改共同文件。

检查覆盖：无项目/未绑定 Product、研究授权失效及 AI 失能、OEM 映射、原值精度、字段对应与成熟度分离、并列冲突、未裁决、部分导入、重复意图与 ID 冲突、来源撤回/权限漂移/版本变化/正文不匹配、位置替换/原件不可用/歧义映射、重复 JSON 原字段、未选来源重核、候选变化/父定义所有者拒绝、显式引用容量限制及 port 缺失。

## 未接入与验收边界

研究持久化/独立 scope、RLS/公共命令与事件注册、真实 Artifact/原件读取和权限锁、具名已接受需求核验、定义所有者/统一预览一次确认、API/BFF/父页面尚须主线接线，详见 [integration.md](integration.md)。没有公共路由或演示 fixture 注入业务页。没有 DB、HTTP、浏览器、构建、真实网页/外部连接/LLM、原件操作或数据外发检查；没有读取 `.env`、`.local` 或凭据，未启停共享服务、安装依赖、commit/push。

当前是可调用独立包候选，尚不能算主线 G1.1 可用闭环，更不能替代 AT-01/03/06、G/N/P/Q 联合/人工出口。后续机会实验、销售 CRM、全网爬虫不在本包范围。
