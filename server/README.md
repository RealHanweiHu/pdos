# 保留的原工程资产

现行后端位于 [`pdos-next/server/`](../pdos-next/server/)。原业务代码、迁移和测试仅在开发机器归档至本地 Git 标签 `original-final-2026-10-08`；归档标签不随本快照发布，不在本目录继续开发。

本目录仅保留共用运行环境入口 `scripts/agent_runtime_environment.py`、原 `golden/` 可信资格材料及本地忽略的运行依赖。共用脚本使用 `packages/pdos-agent-runtime/`，不依赖已删除的原业务模块。原资格不得继承为 PDOS Next 资格。
