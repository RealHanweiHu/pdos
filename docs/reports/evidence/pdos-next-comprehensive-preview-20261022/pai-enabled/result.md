# 统一产品预览 · 小Pai已启用（2026-10-23）

用户要求“帮我开启小Pai”。沿用已核对的人类授权：UI工作会话中用户明确“现在开发阶段，不设MiniMax 上限和费用限制和次数限制”（会话 01a164d2-6ba2-72f3-acb9-9863b4e0b249，用户回复 01a167e9-33ab-72a2-b768-7ec901ad8a9b），结合本会话当前预览启用请求。未复用原S1的 $1 / 8次额度。

## 实际结果

- 入口仍为 http://localhost:57859/ ，同一固定演示身份。独立副本 57358/pdos_test，标记 c351c0ca-b874-49b9-bf1b-44c3ad150aaf。
- 已配置 MiniMax-M3，凭据继续由既有 macOS Keychain 适配器读取。仅当前预览租户绑定，无凭据进入浏览器、证据或仓库。
- 18个当前注册技能经领域命令预览/确认启用；模型配置、钱包也有配置回执。T0资格为0，不增加具名决定权。合成agent的过期品类授权续至既有人类演示账号相同有效期；专业资格未改。
- API和独立worker经 Temporal namespace `pdos-next-comprehensive-20261023` → 已注册LangGraph执行，检查点在本副本独立pdos_checkpoints数据库。不开启其它演示租户的模型配置。
- 开发期不限额来自服务器配置，账本保留，停止控制保留。配置文件 `.local/comprehensive-minimax-20261023.json` 为私有且不入仓。
- 页面实际发送问候，第二次工作 eb0a12df-f177-4de6-abef-16d0867eee6e 已完成，约8秒，返回“你好！我是小Pai，随时可以帮你推进汽车充气泵品类的立项、变更、验证或放行事务。”该文字为模型回复，不作为所有领域能力完成验收的声明。
- 合计3次模型调用、账本 $0.028178、占用0，均只涉及当前合成演示内容，模型执行未产生业务写入。记录见 runtime-verification.json。

## 同时修正与验证

- 原“你好”因至少3字符而无法发送；新工作、个人工作、续接和请求恢复统一接受至少1个非空白字符，服务端仍拒绝空白及超过8000字符。
- 首次问候运行真实失败：模型把问题的depends_on列表返回为空字符串，路由在正式校验之前抛出异常。保留失败记录60dbc38b-9f91-474a-bfd3-702cb161d9c7，不改写为成功。现将无效问题导入既有有限校验重试，不生成无效等待、不新增业务权限。
- 后端输入与图测试19项通过，覆盖无效问题修正成功及耗尽重试降为partial；前端请求恢复5项、续接2项通过；TypeScript及受影响ESLint/Ruff通过。
- 已核对实际页面受理→真实模型→结果可读；不代表全部18技能、全部业务闭环或S1完整验收通过。未重跑整仓构建与全量阶段验收。
- 同期UI工作接入开发期预算标记s0_0814；本副本升级前备份为 ~/pdos-preview-backups/2026-10-23-comprehensive-pai/pre-0814.dump（88,134,341 bytes）。该历史保留，不降级抹除开发用量。

## 本地恢复

使用 `pdos-next/server/.venv/bin/python pdos-next/tools/comprehensive_preview.py api` 或 `worker`，同时传 `--runtime pdos-next/.local/comprehensive-runtime-20261022.json --catalog pdos-next/.local/comprehensive-preview-20261022.json --model-runtime pdos-next/.local/comprehensive-minimax-20261023.json`。不带最后一项仍默认关闭新模型调用。现有web进程保留；进程号与日志在私有.local目录。
