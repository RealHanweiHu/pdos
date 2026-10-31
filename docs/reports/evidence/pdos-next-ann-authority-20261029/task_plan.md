# ANN 当前权限与去重来源续验

本闭环本地机制已完成：固定200分块池来源不足改为小集精确/大集有界扩池；PG16原始距离KNN排序及完整当前权限过滤保留；原SELECT以auto_explain同backend/SQL/顺序/条数匹配计划，不用重放计划归因原返回结果。

8192完整三权限×4查询均与精确来源集合一致，但无实际HNSW，原始结果保留。32768首轮在连续prepared通用计划退化后中断，保留14个脱敏计划及失败，T1与observer恢复通过。已只给nearest/eligible Select加服务器标记，由do_execute使用prepare=False保留参数敏感规划；其他SQL与参数绑定、prepare_threshold、planner成本和RLS保持原路径。

最终101项纯检查、Ruff、独立代码复核通过；新32768完整矩阵5项通过（1项原生/12控制＋4项重叠纯检查），24次capture/39计划匹配。nearest prepared条目0、driver阈值5、其他prepared条目17–25；92输入及此前项目120输入一致。原生T1停用自有profile后向量0，临时观察设置/SET权限完全恢复。

最终8/12组实际HNSW，HNSW-only宏来源recall@5/@10为0.25/0.15，未观察到加速收益。机制与同权限对照收口，ANN质量/性能收益未通过，默认仍关键词；不盲调ef/池/形状制造通过。真实语义质量及默认混合资格待真实同题证据。详见[result.md](result.md)、[最终检查点](native-custom32768/checkpoint.json)及各轮原件。全程无真实模型/embedding调用。
