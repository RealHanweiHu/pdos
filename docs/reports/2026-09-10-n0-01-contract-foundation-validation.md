# N0-01 共同字段合同第一片验证

本报告保留第一片时点结果；可执行候选与manifest已随[产品/计划第二片](2026-09-10-n0-01-product-planning-contract-validation.md)升级，不能把第一片计数当最新完整验收。

日期：2026-09-10。用户要求“按照新的设计开始执行”；本轮由设计阅读进入可执行合同与当前代码盘点。主计划/65项范围不变。N0-01仍部分完成。

## 交付与候选

新增[候选合同与追溯](../contracts/pdos-v1/README.md)、Pydantic校验器、组件OpenAPI、当前metadata/迁移/事件/权限/API盘点、可复现导出器和测试。完整文件及SHA-256见[manifest](../contracts/pdos-v1/manifest.json)。

基准Git HEAD：`8d2ec5c75b9296b86e552582cdc44e69e9bc7d68`，工作树已有大量用户前序改动，因此不把HEAD当本轮完整候选。新候选以manifest中实际文件摘要为准；本轮未提交或push。

静态事实：97表、11namespace、69注册事件、215 API操作、59迁移（含0000脚手架），单head为`0058_ai_test_plan_changes`。这是本地代码声明盘点，不是运行数据库或生产探测。导出器未读取`.env`或业务记录，不连接数据库或外部服务。

本片有16个稳定合同条款N0C-001～016；业务与运行字段分别位于`app/contracts/common_objects.py`、`runtime_records.py`，未被生产路由/执行器导入。OpenAPI仅components，没有伪造未来路由。

## 验证结果

命令均在`server`目录执行。

| 验证 | 命令/范围 | 结果 |
|---|---|---|
| 新合同正反例 | `.venv/bin/pytest -q tests/test_common_object_contracts.py` | 30 passed |
| 合同+旧兼容回归 | 上项加`test_agent_runtime_contract.py test_project_access_policy.py test_rbac_policy.py test_test_report_mapping.py` | 73 passed |
| 静态规范 | `.venv/bin/ruff check app/contracts scripts/export_common_contracts.py tests/test_common_object_contracts.py` | passed |
| 类型 | `.venv/bin/mypy app/contracts scripts/export_common_contracts.py tests/test_common_object_contracts.py` | 5 files passed |
| 导出/漂移 | `.venv/bin/python -m scripts.export_common_contracts`，随后同命令`--check` | 3 artifacts一致 |

正反例覆盖：tenant/scope自报冲突、额外字段、版本/来源缺失、naive时间、排程孤儿/环路/重复、未知工时与估时依据、完成证据/独立接收、DCP/TR结果、四时间批准/事实、供应unknown不当0、指标原值/规则/阈值来源、旧配置不拷当前、授权时效/锚点、Manifest版本/观察、分页失真/工具失能、压缩ACL/回读、等待释放lease、审阅/应用与实际执行分离。组件引用全部可解析。

测试数据为进程内合成对象；未使用数据库，因而未触及开发/生产库。没有迁移或业务运行变更，未启动浏览器、生产构建或真实模型；这些不作为本片纯合同交付的证据。没有宣称完整后端/前端或红队全量门禁通过。

## 剩余与交接

后续继续N0-01完整字段及命令/事件/物理兼容合同，见候选README第5节。再按原N0-02→N0-03/04等依赖实施。当前仅可执行schema骨架，尚不能创建用户的初始计划、启用立项前工作区或修复SIM-GAP-01/02。

本片未正式冻结全部DC决定、未新建迁移、未改变Agent业务零写、未放开预算或出站/真实外发。P1–P6和Q0–Q6保持原状态，D14-04仍29项待测；D14-02历史回放不转为本轮业务结果。没有新增外部权限阻塞；当前剩余是正常合同与实现工作。
