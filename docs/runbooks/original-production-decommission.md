# 原工程生产环境下线

日期：2026-10-08。依据：用户决定"原工程停用关闭"，以及停用步骤 S5"下线生产"（[设计确认稿](../design/2026-10-08-pdos-next-design-confirmation.md) §6）。

**执行要求**：
- 每一步都由用户本人执行，或由用户对该步单独明确授权（AGENTS.md"必须保留的批准与验收边界"）。
- 删除数据库、存储桶、账号属于永久删除，只能由用户本人执行。
- 服务器、Nginx、RDS 实例与 ERP 看板、CEHub（以及同网络的 CRM）共用。**只动 PDOS 自己的部分**，每一步后都要确认其他站点正常。
- 命令中的 `<…>` 是占位符。口令、密钥不写进命令历史、日志或本文件。

## 资源清单（来自 Sprint 0 运行手册与部署脚本）

| 资源 | PDOS 部分 | 共用部分（不要动） |
|---|---|---|
| ECS `8.140.197.68` | compose 项目（`compose.production.yaml`：migrate、api、dispatcher、executor、dingtalk、reminders、schedule-propagation、web）；宿主机端口 `127.0.0.1:3002`；以完整 SHA 命名的发布目录及其 `.env.production` | ERP 看板、CEHub 容器；Docker 本身 |
| Nginx | `pdos.beepump.net` 的 server 块；ACME 路由；证书 `pdos.beepump.net.pem/.key`；只处理该域名的续期 hook | Nginx 容器、其他站点配置、登录限流区 |
| RDS `pgm-2ze135h6045td5ujvo` | 数据库 `pdos`、账号 `pdos_app` | 实例本身；`erp_dashboard`、`cehub` 库及其账号 |
| OSS | 私有桶 `pdos-files`；PDOS 专用的访问密钥（若为专用） | 其他桶、共用的密钥 |
| DNS | `pdos.beepump.net` A 记录 | `beepump.net` 的其他记录 |
| 钉钉（若已创建） | PDOS 企业内应用（独立 agent_id 与回调地址） | CEHub 的钉钉应用 |

记录显示生产停在 8 月版本（`905e888` / 迁移 `0032`），`delivery=false`，没有真实外发。

## 步骤

### D0 现状确认（只读）

1. SSH 登录 ECS，进入当前 PDOS 发布目录（以完整 SHA 命名）。
2. 执行 `./scripts/deploy-ecs.sh status`，记录正在运行的 PDOS 容器、镜像版本和健康状态。
3. 记录 `docker ps` 全量清单，用于最后核对其他系统没有受影响。

### D1 备份生产数据（先于任何停止或删除）

1. 备份 RDS 的 `pdos` 库：在 RDS 控制台创建一次手动备份；或在 ECS 上用 `pdos_app` 账号执行 `pg_dump -Fc`（口令通过环境变量或 `.pgpass` 提供，不写进命令行），导出到本地加密位置。
2. 校验导出文件可读：`pg_restore --list <文件>`；记录表数量和 sha256。
3. 如需保留上传文件，用 ossutil 把 `pdos-files` 桶下载到本地，并核对对象数量。
4. 备份放在 iCloud 之外，建议放在 `~/pdos-preview-backups/2026-10-08-original-final/production/`。

### D2 关闭公网入口

1. 备份当前的 Nginx compose 文件、站点配置、TLS 证书和续期 hook。
2. 从 Nginx 配置中删除 `pdos.beepump.net` 的 server 块（HTTP/ACME 和 HTTPS 两段），以及只服务 PDOS 的上游 `pdos-web:3000`。
3. 在同版本 Nginx 容器中执行 `nginx -t` 校验候选配置。
4. 按 Sprint 0 手册的做法，只强制重建 Nginx 容器（配置是单文件挂载，不能只 reload）。
5. 立刻确认 ERP 看板、CEHub 站点正常访问。
6. 删除只处理 `pdos.beepump.net` 的续期 hook；可选：执行 `certbot delete --cert-name pdos.beepump.net`。

### D3 停止并移除 PDOS 应用

1. 在 PDOS 发布目录执行：`docker compose --env-file .env.production -f compose.production.yaml down`。只作用于 PDOS 这个 compose 项目，不加 `-v`；生产库在 RDS，不在本机卷上。
2. 确认 `127.0.0.1:3002` 不再监听，PDOS 容器全部消失，ERP 看板、CEHub 容器仍在运行（对照 D0 的清单）。
3. 可选：删除镜像 `pdos-api:<sha>`、`pdos-web:<sha>`，以释放磁盘。

### D4 撤销 DNS

在 DNS 控制台删除 `pdos.beepump.net` 的 A 记录。确认解析失效后，公网访问 `https://pdos.beepump.net` 应无法连接。

### D5 永久删除数据和凭据（确认 D1 备份可读后，由用户本人执行）

1. RDS 控制台：删除数据库 `pdos` 和账号 `pdos_app`。不要动实例、其他库和账号。
2. OSS：清空并删除桶 `pdos-files`。若 PDOS 使用专用访问密钥，在 RAM 中禁用并删除；若与其他系统共用，不要删除，只撤销对 `pdos-files` 的授权。
3. ECS：删除 PDOS 的发布目录，以及其中的 `.env.production`（含 JWT 密钥、RDS 账号、OSS 密钥等）。删除前确认 D1 备份已完成。
4. 若已创建 PDOS 钉钉企业内应用：在钉钉开放平台停用或删除该应用，撤销回调地址。

### D6 最终核对

- 公网 `pdos.beepump.net` 不再解析或无法访问；
- ECS 上没有 PDOS 容器，3002 无监听；
- ERP 看板、CEHub 正常，Nginx 错误日志没有新增异常；
- RDS 实例上只剩其他系统的库和账号；
- 备份位置和校验和已记录。

完成后，在设计确认稿 §6 的 S5 一行记录执行日期和结果。
