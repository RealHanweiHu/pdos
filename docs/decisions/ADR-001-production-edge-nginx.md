# ADR-001: 复用现有 Nginx 作为 PDOS 生产边缘入口

## Status

Accepted

## Date

2026-08-11

## Context

原执行计划假设 ECS 已运行 Caddy，并预留 `pdos.beepump.io`。生产核对发现 80/443 实际由 `erp-management-dashboard-nginx-1` 持有，服务器未安装 Caddy；人已将 `pdos.beepump.net` 解析到同一 ECS。PDOS web 仅绑定宿主机回环端口 `127.0.0.1:3002`，而容器化 Nginx 无法通过宿主机内网地址访问该回环端口。

必须同时保持以下边界：

- API 不映射宿主机端口，web 仍只绑定回环端口。
- 不复用两个 Compose 项目都可能拥有的 `web` 别名。
- 不影响 ERP、CRM 和 Hub 的现有站点与证书。
- HTTP 自动跳转 HTTPS，登录入口限流，证书可自动续期。
- 变更可通过恢复备份配置并只重建 Nginx 回滚。

## Decision

经人明确确认，生产域名采用 `pdos.beepump.net`，复用现有 Nginx：

1. PDOS Compose 为 web 增加冻结别名 `pdos-web`。
2. 现有 Nginx 同时加入其原网络和外部网络 `pdos_default`，只反代 `pdos-web:3000`。
3. Nginx 为 `/api/session/login` 与 `/api/session/setup` 复用登录限流区，并设置转发协议、客户端地址和请求 ID。
4. Let’s Encrypt 使用现有 certbot webroot 签发独立证书；部署 hook 仅在 `RENEWED_DOMAINS` 包含 `pdos.beepump.net` 时复制证书、执行 `nginx -t` 并 reload。
5. 继续保留 `127.0.0.1:3002` 作为私有运维 smoke 入口；不公开 API 端口。

## Alternatives Considered

### 在同机新增 Caddy

- 会与现有 Nginx 争用 80/443，必须再引入一层端口转发或迁移全部站点。
- 拒绝：扩大故障域，不符合 Sprint 0 的最小生产变更原则。

### Nginx 反代宿主机 `127.0.0.1:3002`

- 容器的回环地址指向容器自身；现网验证无法访问宿主机回环绑定。
- 拒绝：不可达，且改为公网/全网卡绑定会削弱既定暴露边界。

### 使用共享别名 `web`

- Nginx 同时加入两个 Compose 网络后存在名称歧义，可能把 PDOS 流量发给 ERP web。
- 拒绝：路由不确定且存在跨应用安全风险。

## Consequences

- Nginx Compose 与 TLS 配置属于 ERP 部署目录，修改前必须备份并在候选容器中通过 `nginx -t`。
- 单文件 bind mount 在宿主机原子替换后，运行中容器仍持有旧 inode；配置替换后必须只强制重建 Nginx，不能仅依赖 reload。
- 证书、HTTP→HTTPS、响应安全头、401 错误路径、既有站点回归和至少 30 分钟错误观察均属于 Sprint 0 出口证据。
- 回滚不执行 Alembic downgrade；恢复 Nginx/Compose 备份并重建 Nginx，PDOS 可继续通过回环端口检查。
