# S3 共享整改与正式变更准备检查点

本轮接续 `fafc493`，建设范围是“品类共享 Issue/CAPA → 实际受控政策 → 两项具名 Selection → 保留 unknown 的变更令草稿”。S1/S2/S3 正式验收均未完成；性能验收沿用 P13 暂缓。

## 已实现

- 共享整改按品类受众读取，Current 使用实际 `issue_revision`。新报告捕获证明沿用其固定 Run 受众，原件和完整读集仍须通过现有 ACL/RLS；候选列表与新导入继续限于捕获人。历史私有捕获未被自动改写或扩大权限。
- 增加按实际项目筛选的 Change 索引、订单准备上下文和已登记逐项材料解析入口。读取核对实际政策、CAPA 措施、执行者、Current、来源和具名适用性，不写业务事实或消费确认。
- 页面明确选择项目内 Change，展示实际政策和逐项决定；只采用当前适用的真实计划项，每个已知对象须明确处置、原因及原文。默认 unknown，不能自动改成无需变更；经既有实质预览和一次确认准备订单。
- 具名 Selection 的保留凭证按实际 T2 规则读取，无强制确认时窗；普通确认仍须期限，显式过期或凭证/回执不匹配仍拒绝。未赋予 AI 具名决定权。
- BFF 精确放行两条新路径及项目查询，保留方法/查询/正文校验和原请求恢复。草稿、预览与不确定提交按用户、型号、项目、Change 隔离，恢复保留原 command/key/token。

## 验证

- [后端集中检查](affected-pure-complete-review.log)：256 passed；[源文件校验](affected-pure-complete-review.json)期间本轮文件无变化，进程移除全部数据库 URL。
- [前端/BFF](frontend-affected-final.log)：116 passed；[局部 lint](frontend-lint.log)通过。
- [生产构建及类型编译](web-build-offline.log)通过，使用本机已有 Geist CSS/字体字节的离线 next/font 测试钩子；[输入及 SHA](local-font-inputs.json)已登记，不声称验证了在线字体下载。首次[构建日志](web-build.log)保留 DNS 失败；外网字体请求被自动批准审查以缺少外网授权拒绝，随后未再次外连。
- 固定后端候选与已构建前端的[逐文件比较](web-source-comparison-final.json)：仅其他会话的 `design-qa.md` 文档变化；本轮前端运行源码一致。[交付源码](delivery-source.json)仅另增加 3 项完整预览/真实执行比较的测试文件，未改变实库候选运行源码；该文件已在 256 项中执行，12 项具名凭证回归也包含其中。

[最终实库/API 整链](shared-order-complete-review-browser.log) **1 passed**，五次先前失败不累加为新病例；[元数据](shared-order-complete-review-browser.json)确认所有固定输入运行期间无变化，实际 head `s0_0774`，显式独立 `127.0.0.1:64245/pdos_test` 及原标记已核对。通过真实捕获/Run受众与跨人员读取、他人候选列表不可见、category Issue/CAPA、实际 host Policy、两项 T2 Selection、两条新读取前后业务/确认/回执/审计/Outbox计数不变、T1 Order 原子保存及同回执重放；unknown、旧 Issue 和原测试结果保留，批准/实施记录仍为零。

同一通过现场保留至实际浏览器检查，未使用模拟 GET。页面明确选择本项目 Change 后，显示当前工程/制造政策及两项适用决定；展开实际已保存 Order，显示 0 项专业决定及尚无实际新输出，unknown不被补造为已生效。[亮色截图](saved-order-light.png)、[暗色截图](saved-order-dark.png)、[页面读回](browser-reading.ax.txt)及[结果摘要](result.json)已保存。浏览器仅本地登录/读取/选择/展开及主题检查，未点击业务提交；写入与重放由同场景实际 API 覆盖。本轮没有检查手机尺寸或在浏览器重新办理整份逐对象计划，不宣称这两项通过。pytest时长包含保留现场等候浏览器的时间，不用于性能或SLO结论。

自有浏览器、Web及该夹具 API 已关闭，标记测试库与其他会话/共用服务保留。

## 失败与修正

1. [首轮](shared-order-chain-browser.log)：88.50 秒在同品类工程师读取共享 Issue Current 时失败。真实依赖 RLS 指向硬编码 private 的捕获证明；修复其新写入受众，同时增加候选归属限制及实际跨人员/列表断言。
2. [第二轮](shared-order-proof-audience-browser.log)：91.31 秒已通过共享读取，随后新上下文把持久化来源字典直接交给既有 DTO 读取端口而失败；入口现还原严格 `SourceRef` 后复用原来源检查。
3. [第三轮](shared-order-normalized-source-browser.log)：137.77 秒已保存两项实际 Selection，新读取把其无时限具名凭证当作普通确认而报告待重核。修复操作档位，并用 12 项真实 Confirmation 材料回归保留全部其他一致性守卫。
4. [第四轮](shared-order-named-proof-browser.log)：169.49 秒已通过实际 Selection 读回，订单公共预览把严格 Command 的 `SourceRead` DTO 直接传给只接受字典的读集合并函数而失败；仅在订单读取入口序列化严格 DTO，缺失来源和版本冲突规则保留。
5. [第五轮](shared-order-command-reads-browser.log)：193.96 秒在实际保存处被SQL原子约束回滚。[仅相关数据库诊断](order-write-diagnostic.json)及[真实函数片段](order-atom-function-diagnostic.json)确认 `review.after` 必须等于完整新版本；旧预览仅调用纯核 `_prepare`，漏掉实际 `execute` 追加的版本及History。现在使用实际 History DTO投影同一命令/人/状态/说明及新版本，仍仅遮蔽新保存时钟与具名凭证临时ID，不更改SQL守卫。
6. 后端扩展纯检查最初因旧多 Run 预览夹具缺少当前兄弟 Run 端口失败；仅修正测试夹具为精确当前元组，保留真实快照校验和原时钟/占用断言。最初前端检查命令工作目录错误也保留于 `frontend-affected.log`，改为 Web 目录后 116 项通过。

## 剩余范围

本检查点不含专业批准、新配置实施、实际生效、独立有效性或关闭。下一步按真实覆盖原文及用途修正影响适用范围与真实关系，完成明确对象处置和工程/制造分别批准，再贯通受批准计划绑定的新配置增量、新 Build/请求/Run 及独立验证。不得为 S3 虚构 S4 Pilot/Release，不得简单忽略批准后新增输出触发的依赖时钟变化。

MiniMax 国内 M3 的协议、凭据、资料范围和真实外发授权仍缺；真实模型/资格及 S1 既有 3 项间歇确认失败保留。无新迁移、golden-case 写入、性能采样、重复攻防、git push、生产操作或真实客户资料出站。
