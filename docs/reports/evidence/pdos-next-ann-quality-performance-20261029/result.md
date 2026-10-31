# 来源级权限计算与ANN对照

来源级权威物化已实现并通过实际对照；ANN质量与加速收益未通过，默认保持关键词。全部使用确定性向量，无真实模型或embedding调用。

同一普通app角色、同一RR事务、同一向量和完整授权集合下，新旧exact的有序来源/分块结果完全一致：

| 权限范围 | 原inline | 来源物化 | 主要重复读取变化 |
|---|---:|---:|---|
| owner，512来源 | 9.685s | 2.943s | Artifact PK 32,768次→来源Bitmap 1次/512行；Product 32,768→512次 |
| peer，64来源 | 3.233s | 0.855s | Artifact PK 32,768次→来源Bitmap 1次/64行；audience 30,720→480次 |

时间包括生产semantic_rows与观察器SET回调，不含日志解析、距离标量核对或replay。authority预读会暖缓存，跨角色反转不等于同角色平衡交叉；不能据此宣称生产p95通过。SearchSource仍有按chunk读取与临时文件开销。

同一32,768×384夹具，owner/peer/撤权后三权限×4查询，分别运行strict/relaxed与ef40/128。每次仍使用完整权威过滤、原阈值和200→400→800→1000有界池，不改planner成本、不禁SeqScan、不VACUUM/reindex。

| 设置 | 最终HNSW数/12 | 仅实际最终HNSW宏R@5 | 宏R@10 |
|---|---:|---:|---:|
| strict40 | 6/12 | 0.3000 | 0.1833 |
| strict128 | 5/12 | 0.3200 | 0.1800 |
| relaxed40 | 2/12 | 0.5000 | 0.4000 |
| relaxed128 | 4/12 | 0.4500 | 0.3750 |

四组最终HNSW样本不同。relaxed40的2个样本都来自owner，低权限两阶段没有最终HNSW，不能将较高数值解释为低权限ANN改善。全部返回的实际cosine距离经过另查核对并非递减；无来源不足、重复或越权。四组混合查询的中位耗时约2.13–2.22秒，同题exact约0.86秒；没有依据调整生产ef/mode或启用默认混合检索。

136项受影响纯检查与2项新模式纯检查通过；实际一轮为1项原生＋重复的2项纯检查，3 passed/697.41秒，不重复累计。64次同次SELECT捕获全部匹配，142个nearest实际计划中126个迭代阶段、95个执行HNSW。95项输入在该轮结束时一致；后续关键词query-only改动有独立检查点。原生T1停用后该profile向量为0，512资料/32,768分块及回执保留，临时角色设置与观察权限完整恢复。

原始依据：[实际结果](diagnostic-live/ann-quality-diagnostic-n32768.json)、[同次观察设置与恢复](diagnostic-live/observer-state.json)、[独立复算](diagnostic-live/independent-summary.json)、[原生日志](diagnostic-live/native.log)、[冻结与核对](diagnostic-input-verification.json)、[最终检查点](final-checkpoint.json)。历史低召回、未执行ANN及中断证据保留在[前检查点](../pdos-next-ann-authority-20261029/result.md)。
