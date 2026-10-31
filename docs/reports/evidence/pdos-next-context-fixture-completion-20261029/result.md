# CTX 夹具完成检查点

新候选的四项 focused 原生检查已完成：**4 passed，442.56s**，见 [native.log](native-normalized-20261030/native.log) 和 [tests.xml](native-normalized-20261030/tests.xml)。这证明相应控制断言成立；预期预算停止及未绑定场景仍保留原状态，不等于四格业务场景全部完成。[运行结束核对](native-final-input-verification.json)记录 127 项输入 SHA 全部一致，候选输入见 [frozen-inputs.json](frozen-inputs.json)。本检查点不重写旧 24 格统计。

| 实测格 | 独立复核结果 | 保留状态 |
|---|---|---|
| [CTX-09 / 48k](native-normalized-20261030/CTX-09-F48000.json) | 自然目录一次返回 9 条；独立 cursor 累计 3、6 条，第三次失败 | partial，同一绑定 3→6/9 未齐 |
| [CTX-09 / 64k](native-normalized-20261030/CTX-09-F64000.json) | 同上；不同预算未改变自然边界 | partial，同一绑定 3→6/9 未齐 |
| [CTX-12 / 48k](native-normalized-20261030/CTX-12-F48000.json) | 八份正文的实际区间并集完整；主图 admission 48,379 > focus 48,000 后停止 | partial / CONTEXT_INCOMPLETE，最终回答未完成 |
| [CTX-12 / 64k](native-normalized-20261030/CTX-12-F64000.json) | 八份正文完整读取并完成离线控制流；无预算停止 | bound / native_control_checks_passed，pressure not_triggered |

CTX-09 两档均核对到九个不同的 current 目录对象、版本 2，六个 Q-301–Q-306 引用与真实 Reference 的完整 JSON 相等；7–9 只有 `not_provided` 元数据，未登记未披露正文。三个控制各属不同 Run：长对象机械控制的 origin 只有一个对象，第 1、2 页使用相同 handle，摘要与原 READ 匹配，第三页前执行原来源复核后受控失败。实际交付 7,751 / 11,111 字符，按原 JSON 前缀独立解析，两次累计完整对象数为 `[0, 0]`。真实九条目录自然一次交付完整 JSON，累计 `[9]`；另一个原生 cursor 控制累计 `[3, 6]` 后第三次失败，未交付 7–9。不能把这三组证据拼成同绑定场景通过。

CTX-12 采用 `category_scoped_read_without_fixed_pins`。复审从冻结题集独立重建八份正文，再按实测 locator 区间计算并集，并交叉核对 READ call ID、内容 SHA、原生 revision 1 与 `assistant_extract` binding：两档均为 8 × 4,695 = **37,560 字符**全覆盖，32 次 passage READ；history 核发 8 个引用，final 核发 16 个 `exact_code` 引用，对应八个不同来源。归档自称版本与原生登记 revision 仍分开。

48k 已执行 54 次离线 provider dispatch（main 6、extract 48），之后主图合法停止；仅记录到 8 条已完成 extraction ranges，不能凭正文覆盖宣称后续提取回传或最终回答已完成。64k 为 55 次（main 7、extract 48），控制流完成但没有触发清理对比。八份显式固定 pins 的旧 1,500-token 工作状态上限诊断仍独立保留，不能用本次 category-scoped 结果替代。

三次历史夹具失败保留，不覆盖原日志：

- [native-live](native-live/native.log)：`private_source_in_shared`，共享知识引用了不合法来源类型；后续改为正常登记的品类可见 Artifact。
- [native-final](native-final/native.log)：`material_version_moved`；相同占位内容经原生命令语义去重形成同一 lineage，后续 supersedes 版本冲突。后续以九个不同原生意图建立目录，再按真实服务器顺序合法升版。
- [native-distinct](native-distinct-20261030/native.log)：九条业务目录创建/升版后，引用完整相等断言失败。夹具五字段未包含 Reference 默认 `statement: null`；现按真实模型规范化，完整引用核对保留，相关主测试改为完整列表相等。[3 项纯检查](reference-normalization-pure.log)及 [Ruff](reference-normalization-ruff.log)通过，修复源码 SHA 固定于候选清单。

独立复审只读既有 JSON/日志并使用标准库计算，没有调用数据库、模型、embedding 或网络，也未修改源码、活动清单、旧矩阵及其他总审计。全部 provider 均为脚本控制，usage 零值仅占位；答案正确性、引用语义、真实 usage/延迟/成本、真人资格及压力改善均未评分。详细机器记录见 [final-checkpoint.json](final-checkpoint.json)。
