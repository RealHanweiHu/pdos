# 现场反馈来源检查点（继续验证）

已合入原生现场反馈/处置来源、Outbox投影、签名引用与隔离提取、真实依赖/客户分类、一跳与当前对象入口；通用检索现在为十类来源。

[844迁移](migration-0844.json)备份及实际往返通过，[有历史时降级拒绝](nonempty-downgrade-0844.json)通过，历史计数和函数权限保持。18项交叉纯检查通过；[实际第二轮](pg-run2.xml)新增5项原生用例全部通过。

恢复组在旧category.knowledge.add夹具处失败。只读错误插件取得SQLSTATE23514与调用栈：可选answer_sources的JSON null进入严格数组resolver。对应可空JSONB绑定与caller归一化正在修复；不放宽resolver。十类规模/p95/Temporal恢复尚未通过。另已合入知识visibility十类SQL候选与1项原生跨知识测试，待真实下一迁移和实际执行。

第一轮新FieldClient继承了只处理结构事实的as_of断言，已修为按真实未结构化引文完成答复；未给工具结果添加虚构字段。详见保留的首轮失败与第二轮5项通过。
