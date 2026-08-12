# Sprint 0 ECS 空应用与登录页 Smoke

本运行手册只用于 Sprint 0 人工出口。任何 ECS、RDS、OSS、Nginx 或 DNS 操作都必须先取得人的**明确授权**；自动测试不得使用生产凭据或生产数据库。

## 1. 人工前置条件

- RDS 已创建独立数据库 `pdos` 与普通账号 `pdos_app`，并在该库验证 `CREATE EXTENSION IF NOT EXISTS vector`。
- OSS 已创建私有桶 `pdos-files`；应用凭据没有建桶权限。
- ECS `8.140.197.68` 上 Docker/Compose 正常，`127.0.0.1:3002` 未占用；不对公网直接暴露 API 端口。
- `pdos.beepump.net` 的 DNS A 记录由人确认指向 ECS；现有 Nginx 变更前先备份 Compose、TLS 配置和证书 hook，并执行候选配置校验。
- 服务器上的 `.env.production` 由 `.env.production.example` 复制后填写，权限设为仅部署账号可读；不得提交或复制回工作区。

## 2. 发布前检查

1. 记录待部署完整 commit SHA 和当前线上 commit。本地只用 `./scripts/package-release.sh` 从该 git commit 生成 Git bundle；禁止 rsync/cp 当前工作树。bundle 保留 Git commit/tree 对象，传输或内容被修改后不能继续解析为同一 SHA。
2. 确认 `DATABASE_URL` 使用 `pdos_app`、数据库名 `pdos`、`sslmode=verify-full` 与容器内 CA 路径。
3. 确认 `JWT_SECRET` 至少 32 字节且与开发值不同；确认 `APP_PORT=3002`。
4. 在本地隔离的 `pdos_test` 运行 `make verify-sprint-0`，全部门禁全绿后执行 `./scripts/package-release.sh`，只上传生成的 `pdos-<full-git-sha>.bundle`。
5. ECS 必须先 `git bundle verify`，再从 bundle clone 到一个全新、以完整 SHA 命名的目录；复制现有 `.env.production` 后保持 `0600`，并把其中 `PDOS_IMAGE_TAG` 设置为同一完整 SHA。不得覆盖旧目录。示例：

   ```bash
   export PDOS_RELEASE_SHA='<full-git-sha>'
   export PDOS_RELEASE_DIR="/opt/pdos-releases/${PDOS_RELEASE_SHA}"
   export PDOS_VERIFY_DIR="/opt/pdos-release-verification/${PDOS_RELEASE_SHA}"
   test ! -e "$PDOS_RELEASE_DIR"
   test ! -e "$PDOS_VERIFY_DIR"
   install --directory --mode 0750 /opt/pdos-release-verification
   git init --bare "$PDOS_VERIFY_DIR"
   git -C "$PDOS_VERIFY_DIR" bundle verify "/secure-upload/pdos-${PDOS_RELEASE_SHA}.bundle"
   git clone "/secure-upload/pdos-${PDOS_RELEASE_SHA}.bundle" "$PDOS_RELEASE_DIR"
   test "$(git -C "$PDOS_RELEASE_DIR" rev-parse HEAD)" = "$PDOS_RELEASE_SHA"
   install --mode 0600 /opt/pdos/.env.production "$PDOS_RELEASE_DIR/.env.production"
   cd "$PDOS_RELEASE_DIR"
   # 用权限保持型编辑器将 PDOS_IMAGE_TAG 改为 $PDOS_RELEASE_SHA
   ./scripts/deploy-ecs.sh build
   ```

   `build` 会先验证 Git HEAD 等于配置 SHA，且除 `.env.production` 外不存在 tracked 修改、untracked 或 ignored 文件；再构建带 `org.opencontainers.image.revision` 标签的 API/Web 镜像并复核标签。任一不一致都禁止 migration/up，检查不打印配置值或 secrets。

## 3. ECS 启动顺序

`scripts/deploy-ecs.sh` 是生产发布的唯一受控入口。构建通过后，记录授权对应的 commit SHA；只有取得本次生产部署的明确授权，才设置一次性确认口令并执行：

```bash
export PDOS_DEPLOY_CONFIRM=deploy:<git-sha>
./scripts/deploy-ecs.sh deploy
unset PDOS_DEPLOY_CONFIRM
./scripts/deploy-ecs.sh status
```

脚本固定按 `生产配置预检 → Alembic migrate → 重施加并验证 Agent 最小权限 → api/dispatcher/executor healthy → web healthy → 本机/公网 smoke → 最近 10 分钟错误模式扫描` 执行。任何一步失败即停止。运行服务使用 `--no-deps`，不会隐式重跑迁移器；`api` 仅在容器网络暴露 8000，宿主机只绑定 `127.0.0.1:3002`。

只需检查现状时运行 `./scripts/deploy-ecs.sh status`；只需在已构建镜像上重跑完整配置预检时运行 `./scripts/deploy-ecs.sh preflight`。禁止绕过脚本直接执行 `docker compose up`。

## 4. 公开前初始化、Nginx 与 smoke

若 `/api/session/status` 返回 `needs_setup: true`，此时不得先发布 DNS/Nginx。由人通过 **SSH 端口转发**访问宿主机回环端口，例如：

```bash
ssh -N -L 43002:127.0.0.1:3002 <deploy-user>@8.140.197.68
```

人在本机浏览器打开 `http://127.0.0.1:43002/login` 完成唯一一次 setup，确认状态变为 `needs_setup: false` 后关闭隧道。生产管理员密码只由人输入；不得出现在命令、任务消息或日志中。只有完成这一公开前初始化，才能开放域名入口。

PDOS web 在 `compose.production.yaml` 中使用冻结网络别名 `pdos-web`。现有 Nginx Compose 只把 Nginx 服务接入外部网络，不能把两个应用都存在的共享别名 `web` 当作 PDOS 上游：

```yaml
services:
  nginx:
    networks:
      - default
      - pdos

networks:
  pdos:
    external: true
    name: pdos_default
```

同一共享网络内 ERP 与 CRM 也都曾占用通用别名 `web`；ERP 主站的 Nginx 上游必须使用唯一 DNS 名 `erp-management-dashboard-web-1:3000`，不得继续使用 `web:3000`。

Nginx 为 `pdos.beepump.net` 提供 ACME HTTP-01 路由和 HTTPS 反代；登录与 setup 入口复用文件顶部的登录限流区：

```nginx
server {
    listen 80;
    server_name pdos.beepump.net;

    location /.well-known/acme-challenge/ {
        root /etc/nginx/certs/acme;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    http2 on;
    server_name pdos.beepump.net;
    resolver 127.0.0.11 valid=10s ipv6=off;

    ssl_certificate     /etc/nginx/certs/pdos.beepump.net.pem;
    ssl_certificate_key /etc/nginx/certs/pdos.beepump.net.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    location ~ ^/api/session/(login|setup)$ {
        limit_req zone=login burst=5 nodelay;
        set $upstream_pdos pdos-web:3000;
        proxy_pass http://$upstream_pdos;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }

    location / {
        set $upstream_pdos pdos-web:3000;
        proxy_pass http://$upstream_pdos;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

先用 HTTP-only 候选配置通过 `nginx -t` 并重建 Nginx，再执行：

```bash
certbot certonly --webroot \
  --webroot-path /opt/erp-management-dashboard/deploy/certs/acme \
  --domain pdos.beepump.net \
  --cert-name pdos.beepump.net \
  --non-interactive --agree-tos --no-eff-email
```

证书复制进 Nginx 挂载目录后，最终 TLS 候选配置必须先在同版本 Nginx 容器中通过 `nginx -t`。由于 Nginx 配置是单文件 bind mount，宿主机原子替换会更换 inode；应用最终配置时必须只强制重建 Nginx，不能仅依赖 reload。续期 hook 必须按 `RENEWED_DOMAINS` 只处理 `pdos.beepump.net`，复制证书后先 `nginx -t` 再 reload；`certbot renew --cert-name pdos.beepump.net --dry-run` 必须通过。

依次验证：

- 宿主机 `/login` 返回 200 且标题为 `登录 · PDOS`。
- 宿主机 `/api/session/status` 返回 `needs_setup` 布尔值。
- 公网 HTTPS `/login` 返回 200，证书有效，HTTP 自动跳转 HTTPS。
- 浏览器完成 login→me→首页；密码与 JWT 不出现在页面、响应体或日志。
- `./scripts/deploy-ecs.sh status` 通过，最近 10 分钟的 api/dispatcher/executor/web 日志无 traceback、fatal、panic、权限拒绝或连接拒绝。

setup 会创建生产管理员，是一次性业务写操作；必须由人确认账号信息并在私有隧道的浏览器中执行，Agent 不代填生产密码。

## 5. 成功判据与观察

- migration 完成且只有一个 Alembic head；API/web health 均为 healthy。
- 只有 `127.0.0.1:3002` 监听应用流量，8000 不映射到宿主机。
- 登录关键路径成功，错误密码返回稳定 401，事件与不可变审计仍同事务留痕。
- Nginx 上线后至少观察 30 分钟：5xx、容器重启、数据库连接错误与 Nginx 错误日志均无新增异常。

## 6. 回滚

触发条件：健康检查失败、持续 5xx、登录不可用、数据完整性异常或安全边界异常。

1. 保留数据库，不在事故处理中执行 Alembic downgrade；先确认旧应用镜像与当前 schema 前向兼容。
2. 取得本次回滚的明确授权，使用部署前记录的镜像标签执行下列命令。回滚入口只替换运行服务，明确不启动旧迁移器：

```bash
export PDOS_ROLLBACK_IMAGE_TAG=<previous-git-sha>
export PDOS_ROLLBACK_CONFIRM=rollback:<previous-git-sha>
./scripts/deploy-ecs.sh rollback
unset PDOS_ROLLBACK_CONFIRM PDOS_ROLLBACK_IMAGE_TAG
```

首次采用 revision 标签前的旧镜像没有 OCI revision。该一次性兼容回滚会额外给出同时绑定旧 tag、API image ID、Web image ID 的 `PDOS_LEGACY_ROLLBACK_CONFIRM` 期望值；必须由人核对部署前记录的两个 image ID 后再设置。标签存在但与 tag 不同的镜像永不允许回滚。

3. 若新 Nginx 配置导致故障，恢复 Nginx Compose、TLS 配置和 hook 备份，校验后只强制重建 Nginx。
4. 复查 `/healthz`、`/login`、`/api/session/status` 与日志；记录故障时间、commit、迁移 head 和处置结果。

若 migration 已引入不可向后兼容变化，应停止发布并走修复迁移，不得通过复用迁移号或手工改 schema 回退。
