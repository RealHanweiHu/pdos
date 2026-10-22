# 测试报告后台导入

本地候选 0094。陌生 Excel 模板支持上传回执、后台映射、生成待确认批次、查询与取消；正式测试结果仍由原确认操作产生。

部署候选需要先完成迁移，并配置预算模式的 application worker 与私有对象存储读/写/删除权限。准备完成后，Web 的 `PDOS_AI_REPORT_IMPORT_ASYNC=true` 将现有上传表单转至后台入口；默认 false。本文不授权部署或真实模型调用。

- `POST /api/projects/{project_id}/npi/test-import-requests` 接收 `plan_id` 和 `.xlsx`，最多 20 MiB，返回 202。陌生模板返回 run_id；内置/已确认模板、相同内容已有批次直接返回 batch。
- `GET /api/projects/{project_id}/npi/test-import-requests/{run_id}` 返回发起人的处理状态和批次。页面保存该 run_id，刷新后继续查询；网络失败暂停轮询并提供重新查询。
- `POST /api/ai/runs/{run_id}/cancel` 复用应用取消。页面“取消导入”调用此入口；已经完成的批次按原状态查看。
- `PYTHONPATH=. .venv/bin/python scripts/run_application_worker.py` 在 Chat、风险与测试计划后处理报告队列；`--once` 执行一轮。

上传在入队时冻结原预算和授权，不持有运行租约。私有临时对象位于租户/项目下的 `application-inputs/{run_id}/source.xlsx`；读取有大小上限，并复核字节数与 SHA-256。数据库仅记录对象键和回执。

后台领取租约后执行映射。已保存的模型结果可在原预算、授权和版本下恢复，无需再次调用模型。批次写入前复核运行租约和预算；批次与成功回执在同一事务提交。映射完成不单独结束运行，取消仍可阻止后续草稿写入。

完成、取消或确定失败后清理临时对象；成功批次的正式私有文档保留。删除失败保留未释放标记，后续轮次重试。状态与 `application_import_inputs` 的 batch_id/error_code/resolved_at/released_at 可用于排查；不得通过新建同一请求来重置原预算。

N0-03 尚有其他等待点、事件控制及完整 RunControl；统一对话中的文件输入入口与业务链验收继续归对应 N 项。
