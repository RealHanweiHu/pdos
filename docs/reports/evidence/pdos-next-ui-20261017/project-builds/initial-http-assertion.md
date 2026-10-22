# 初次 BFF 检查的预期修正

首次本机 HTTP 检查前 7 项通过，第 8 项预期错误：检查脚本要求 verification-results 对额外 project_id 返回 422，实际返回 200。

读取现有 BFF 后确认：该已有入口只转发 build_id / run_id，其他查询不参与领域范围。本轮未改 BFF。复核改用随机其他 project_id，响应逐字结构等于原显式 Build 的实际领域响应；没有扩大范围或取得其他项目记录。另用非法 run_id 完成验证。最终 9 项见 actual-bff-http.json，与初次重叠不累加。

这是检查脚本的错误假设，不是领域 API 修改。未检查或声称省略 build_id 必然被服务端拒绝；本轮前端始终显式选择 Build 才读取结果。
