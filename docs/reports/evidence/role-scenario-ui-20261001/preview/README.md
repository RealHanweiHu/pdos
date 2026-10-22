# 独立合成岗位预览

[登录预览](http://localhost:3024/login)。租户 `role-preview`，账号 `owner`、`engineer`、`quality`，密码均为 `RolePreview@20261001`。账号与密码只用于本轮临时合成库。

浏览器推荐始终使用 `localhost:3024`。Cookie 按主机隔离，不按端口隔离：另一会话预览的 `127.0.0.1:3023` 与本预览的 `127.0.0.1:3024` 可共享同名 Cookie，导致不同临时库签发的登录令牌互相覆盖。使用 `localhost` 可保留各自登录状态；不修改或清空旧预览的 Cookie 和服务。切到新主机后需要在该主机正常登录一次。API 内部地址仍为 `127.0.0.1:8894`，数据库目标不变。

前端 `127.0.0.1:3024`，API `127.0.0.1:8894`，数据库为新容器 `pdos-role-ui-preview-20261001-c73e` 内的 `pdos_test`，只映射 `127.0.0.1:57441`。真实迁移版本 `0416_product_evidence_item_decisions`。完整目标、合成记录 ID 和凭据见 [metadata.json](metadata.json)。旧预览 `3023/8893/57439` 和存续库 `57432` 均未连接或操作。

三个身份均加入同一合成项目。工程身份有阻塞整改任务，质量身份有今日任务和另一身份负责的问题独立验证，负责人有协调任务和风险。Build → 单台样机 → 不可变配置修订 → 合成失败 Run 已保留实际外键。所有标题与说明标明合成，不代表真实测试、批准、计划验收或业务资格。

API 启动脚本清除继承环境，并在导入应用前设置 `Settings.model_config["env_file"] = None`，阻止 Settings 默认 dotenv 来源，等效于该来源的 `_env_file=None`。数据库和 JWT 只使用本轮合成值。前端 `src` 实体复制自主会话最终冻结候选 `/private/tmp/pdos-role-scenario-ui-20261001-_npy8ks1/web/src`，1066 个源码文件逐字 SHA256 核对一致，见 [source-snapshot.json](source-snapshot.json)。`public/node_modules` 指向同仓库文件，Next 配置原样复制；它有独立 tsconfig 副本、生成声明和 `.next`。该目录没有 `.env` 文件，Next 不加载旧预览凭据。没有修改产品源码或原配置。

证据：迁移成功日志 [migration.log](migration.log)、首次缺无权限角色日志 [migration-missing-agent-role.log](migration-missing-agent-role.log)、合成夹具 [seed.py](seed.py)、初始夹具回滚日志 [seed-initial-fixture.log](seed-initial-fixture.log)、成功记录 [seed.log](seed.log)、启动记录 [startup.log](startup.log)。迁移要求的 `pdos_agent` 仅在新容器创建为 `NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION`，未授予权限、真实资格或登录能力。

仅进行了这个新预览的登录与本人队列 HTTP 可达核对，结果保存到 [http-checks.json](http-checks.json)。没有运行 repo 数据库测试、worker、调度器、AI、批准、发布或外发。浏览器角色与多尺寸检查由主会话另行记录。

质量身份的测试 Run 与文档 GET 用独立 HTTP CookieJar 在 `localhost:3024` 另行核对，并与新 API8894 的独立登录读取相对照：两个入口均为200，Run 1条、文档0条；不输出或保存令牌，结果见 [http-quality-runs.json](http-quality-runs.json)。独立客户端首次使用系统默认代理时在登录阶段超时、未取得令牌；显式禁用代理后一次完成，只连接上述两个新服务。首次三身份可达脚本记录的是 `127.0.0.1` 内部监听地址；面向浏览器的入口以 metadata 的 `browser_url/login_url/project_url/quality_url` 为准。主会话浏览器也已在 localhost 实际读取第1次合成失败测试、配置版本1、登记人与时间。

主会话最终修正 `Ctrl+Home` 的任务导航处理后，已将 `project-task-workspace.tsx` 及其专属测试同步到冻结候选和预览。对应两份 SHA 已在 source-snapshot 刷新；1066 文件重新核对，冻结候选、记录清单和预览实体副本全部一致。本子任务未修改产品源码，也未重启服务。

初次采用 `src` 软链接时，Next 路由扫描只登记 `/_not-found`，首页和登录 BFF 返回404；没有宣称首次启动可用。随后仅将新预览源目录改为已验证候选的实体副本并重启一次3024，登录页及三个身份 BFF 全部200。首失败 [http-checks-symlink-404.json](http-checks-symlink-404.json)、[frontend-symlink-failure.log](frontend-symlink-failure.log) 与恢复 [frontend.log](frontend.log) 保留。原 Next session36755 已结束，恢复后为60727；API与新PG保持原会话运行。

## 保留与后续收尾

预览继续运行供查看；此处仅记录后续操作，没有执行收尾。API exec session `46799`（PID23454），Next exec session `60727`（PID26258）。后续先确认两个 session 仍是本预览，分别发送 Ctrl+C。仅停止并移除 `pdos-role-ui-preview-20261001-c73e`；容器数据库使用 tmpfs，没有业务备份需要恢复，不使用 `docker compose down` 或其他环境名称。保留证据与夹具文件。其他会话服务、旧预览及存续数据库保持原状。

重新准备只能新建同标签独立空库，并显式核对目标；seed 会拒绝非 `127.0.0.1:57441/pdos_test` 或非空租户库。启动脚本和 prepare_frontend.py 的仓库位置均按本证据目录解析，启动示例路径需使用引号保护 `&`。
