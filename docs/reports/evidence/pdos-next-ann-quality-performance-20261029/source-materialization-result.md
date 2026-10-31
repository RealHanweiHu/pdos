来源级权威物化的最小候选已实现，性能尚待主会话实际 PostgreSQL 对照。

`readable_chunks` 新增服务器内部 `materialize_authority=False`；仅 `semantic_rows` 显式开启。默认及固定批次读取保持 inline。开启时先复用原 15 项输出 metadata，并保留 tenant_id、original_ids、created_at，形成 18 列来源级 MATERIALIZED CTE，不存 body/structured。普通 RLS、scoped_authority、安全原件集合、chunk/state/hash/category/版本过滤均未变；KNN membership、分块池、阈值和 prepare 策略未改。

新增 5 项纯检查全部通过，已包含在受影响 9 文件的 136 passed / 1 原生 deselected 中，不重复累计。测试实际编译 artifact 与完整来源族的 SQL，核对来源级投影、原 authority/where/join 守卫、固定批次路径及 exact/iterative 调用。3 文件 Ruff 和 Python syntax 检查通过；未配置静态类型检查器。日志、XML、调用和源码 SHA 见同目录 source-materialization-* 文件。

本代理没有运行 DB、Docker、Temporal、模型或 embedding，也不赋予性能、ANN recall 或质量通过。主会话可在同夹具将 semantic reader 收到的 True 改为 False、其他参数原样透传，得到旧生产对照；应验证 source/RLS loops、buffers、temp、实际耗时及全部权限/来源结果。
