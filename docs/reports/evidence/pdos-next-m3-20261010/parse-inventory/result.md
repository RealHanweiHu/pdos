# M3 失败原件解析库存（parse_manifest 落库）

从 `24effa3` 续建，期间 `d4b864e`（纯前端导航重组）落盘，无后端重叠且已含入下方全量回归；迁移链真实 head 前进到 `s0_0758`。解析器现在声明它实际检查过的全部位置：文本逐行、PDF 逐页（含无文本页）、XLSX 逐已产出单元格；库存经隔离子进程协议往返后随解析事务写入 `uploaded_originals.parse_manifest`（形状受 `uploaded_originals_parse_manifest_shape` 约束），NULL 一律表示范围未知（既有历史行与失败解析保持诚实未知，不回填）。`seal_for` 把库存逐项核对进 `ArtifactSeal`（形态异常按 `INTEGRITY_MISMATCH` 拒绝），覆盖报告据此给出精确的已知/未知范围：`PARTIAL_TEXT` 原件的 `unrepresented` 列出解析器声明而未见文本的位置，`fully_represented=false`、`reason=PARTIAL_TEXT`；无库存时仍报 `parse_manifest_missing`。修复了上一段发现的定位缺口：引文定位文本 `page:N`、`cell:["工作表","B2"]` 现在经 `locator_from_text` 解析匹配定位映射，PDF 原件的抽取行可逐字核对。隔离解析容器镜像按现行源码重建并重新钉住（`parser-image.json`，`built_local_unqualified`）。抽取派发与精确重放对部分解析原件全链通过；真实模型调用 0 次，未授予资格。

- [最终 6 项纯检查](pure-1.xml)：文本/XLSX/PDF 库存（含无文本页与 needs_ocr 保范围）、混合基线拒绝、隔离协议往返、seal 库存形态守卫。
- [最终 4 项实库检查](pg-1.xml)：真实上传/扫描/解析后行库存与页库存落库及 seal 覆盖；`PARTIAL_TEXT` 的 represented/unrepresented 精确拆分；失败解析无 Artifact 且库存为 NULL；部分解析原件的真实派发（page:1 逐字行）与逐字节重放一致。
- 迁移往返：0757→0758→0757→0758 在核对标记库真实执行，列/约束逐段核验；约束负例（缺键、非法基线）与正例（合法库存、NULL）在域会话内逐一验证。
- [受影响 93 项定向回归](affected-1.xml)（抽取派发/页/原件绑定、证据处理、原件安全、持久证据）与[全量 1530 项 agent_kernel + 证据套件](full-regression-1.txt)通过；[规范检查](python-lint-1.txt)通过。首轮全量有 1 项公共 PDF 容器用例因镜像未随源码重建失败，按现行源码重建镜像后通过。
- [源码清单](source-manifest.json)固定本段 1802 份源码（前置 `d4b864e`）。仅使用核对标记的 `127.0.0.1:64245/pdos_test`（marker `f9048729`），无前端/构建产物变化。

开发期缺陷（均未出库）：JSON 协议未携带库存字段（首轮失败）、PDF 测试构造缺 NameObject 包装、挂载引文与 PDF 派生文本不匹配、脱离会话的 ORM 读取、`page:`/`cell:` 定位文本无法参与引文核对（真实缺口，已修并加回归）、冻结工具输出目录写死导致上一段清单被短暂覆盖（已恢复并参数化）。

本段完成失败/部分原件的解析库存。抽取 Claim 消费证明、标准品匹配仍未启用；继续该接线及平台、AT/演示/性能；无 push、生产、真实外发，M3/S1 未完成。
