# Backend: Change similar history and unsaved title hints

已直接实现本次两个明确入口。沿原 ordinary RLS 检索、编号通道、登记关系扩展及五张固定卡片；不读取模型、不创建 Run、不发生出站。变更详情以实际固定 Change 版本标题/原因查询，排除整个自身逻辑对象及已登记关联问题/CAPA，结构字段缺失继续“未记录/待复验”；不从聊天或标题推断根因、工况或业务来源。

协议已与前端代理对齐：

- 原 Issue URL/anchor/反馈请求和指纹保持。新 Change `GET /v1/categories/{category_id}/products/{product_id}/change-execution/{change_id}/similar-history?version_id=...`，anchor 使用 kind=change/change_id；同路径 `/feedback` 使用原六字段，但服务器和卡片均禁止 merge_prepared。
- 新建 Issue/Change `GET /v1/categories/{category_id}/products/{product_id}/similar-history?kind=issue|change&title=...&project_id=...`。标题 trim 后必须1–240字符，不静默截断；服务器核真实 Product 和可选 Project。draft anchor 只含 kind/title/真实范围，没有对象ID、版本或反馈身份；只读，无 draft POST。
- 反馈复用原私有 append-only 表：真实 Issue 或 Change typed 三字段严格二选一，Change 为固定实际版本 FK；无 origin JSONB、无新表，不扩大 agent/其他主体权限。root 已报告851真实备份/往返和原历史保持；本 agent 未连接 DB，也未修改冻结851。

验证：backend-pure.txt 为27通过（原11+新16），backend-ruff.txt 为7项修改/新增文件显式仓库配置通过。backend-pg-collect.txt 收集原8+新4共12 nodeids，尚不代表本 agent 实际PG通过。原两个未修改测试文件有既有 I001 排序问题，不以整目录Ruff通过冒充本包范围。精确源码输入见 backend-inputs.json。

新增原生 PG 夹具 similar_change_pair 使用已有 change_work→quality/results 链、原API/security/report_store，创建两条真实Change和一条未关联Issue；.first/.second为原生receipt，.change_ids为实际逻辑身份，.app为原TestClient.app。root可在首个新case的call hook持有同fixture检查浏览器，无模型/worker。新PG覆盖当前来源/受众、排除自身和已有关系、本人反馈幂等/冲突/真实Change版本/禁止merge、草稿无身份/无业务写、低权限无痕迹。性能集中一项，对Change及两种draft各5warm+40measured，inclusive p95≤1秒，SQL计数须恒定，全部原HTTP请求纳入计时。

剩余由root统一执行本候选真实PG、原Issue回归和浏览器验收；未宣称两份设计或切片E整体完成。未改唯一清单或CEFG报告。
