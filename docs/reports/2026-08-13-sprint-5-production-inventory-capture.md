# Sprint 5 生产 CEHub 全量清单只读捕获报告

日期：2026-08-13
结论：**只读 capture 通过；状态为 `review_required`，等待 Data Owner 批准。未部署、未迁移、未写目标库。**

后续状态：Data Owner 已批准本报告的 inventory fingerprint 与有序四项目，但 release `2cce...` 随后因 CEHub 导入 Project API 阻断失效；本报告保留为历史清单证据，不授权部署/apply。见 `docs/reports/2026-08-13-sprint-5-project-api-release-blocker.md`。

## 授权与 release 身份

- 人工授权：合并 PR #4，并使用最终 release SHA 在 ECS `8.140.197.68` 仅执行 CEHub 全量只读 inventory capture；不部署、不写目标库。
- PR #4 以 merge commit 合并，最终 release SHA：`2ccefa1d2fe6567be4af8370b67aed9164aadd1d`。
- merge parents：`c71c7308eb01ba603e19628d674000a9903234fd` 与已审计提交 `bb15550617c6b1fc3ba6628a76800fdf40219826`。
- Git bundle SHA-256：`15402145b945fbcf938fe82c88e502d87de2ae71490c3ddd1954f4a77db55ee6`；本地与 ECS 完全一致，远端 `git bundle verify` 通过。
- API image：`sha256:b69df7c1038709991e5f968280cd940dc466fa770322acab687c8a0797375df0`；OCI revision 精确等于最终 release SHA，运行用户为非 root `pdos`。

## 全量清单

capture 查询 CEHub `projects` 全表，不按 archived 或试点项目过滤。结果：

| source id | project number | category | phase | archived | lifecycle |
|---|---|---|---|---:|---|
| `WqWcl0wK` | `D14-04` | `npd` | `concept` | false | active |
| `aBnbEdQG` | `S18-01` | `npd` | `concept` | false | active |
| `xY8-PGbc` | `D15-05` | `npd` | `concept` | false | active |
| `zGpNH0Xq` | `C4s` | `obt` | `intake` | false | active |

- project count：4；active：4；archived：0。
- 未发现 v1 不支持的项目类型，`errors=[]`。
- inventory fingerprint：`a450122f0f3bac6a7eceec600463e641f3d33b6768bf1400c81c805b878f484d`。
- 原始报告 SHA-256：`e0375552b2e48d221e7ed800a2b1b5fa9e76c90625fa20f6d03d9596201cfdaf`。

## 安全与零变更证据

- capture 容器采用 `--read-only`、`no-new-privileges`、非 root 用户和私有报告挂载；源 adapter 成功验证独立账号 `default_transaction_read_only=on`、五张表 SELECT-only 且无写权限。
- capture CLI 仅构造 CEHub source engine；`DATABASE_URL` 只用于生产端点/异库/异账号/CA 合同校验，不建立目标 engine。
- 报告在 ECS 为 UID/GID 10001、mode `0600`，路径为 `/opt/pdos-migration-reports/2ccefa1d2fe6567be4af8370b67aed9164aadd1d/cutover/cehub-cutover-inventory-capture.json`。
- capture 前后 5 个线上容器的名称、image tag、container ID 均未改变，继续运行 release `a34c7eb06aaba036bef8c257c30a841c1ec6be0d` 且 healthy；候选 image 无运行实例。
- 生产数据库 Alembic 仍为 `0027_dingtalk_hardening (head)`；未执行 `deploy`、`migrate`、`compose up`、CEHub 写冻结或 DingTalk 外发。

## Data Owner Gate

建议冻结后续有序 selector 为：

`WqWcl0wK,aBnbEdQG,xY8-PGbc,zGpNH0Xq`

下一步必须由 Data Owner 明确批准上述四项、顺序和 inventory fingerprint。批准后仍需单独授权 CEHub 写冻结、inventory verify 与最终全量 dry-run；本报告不构成这些生产操作授权。
