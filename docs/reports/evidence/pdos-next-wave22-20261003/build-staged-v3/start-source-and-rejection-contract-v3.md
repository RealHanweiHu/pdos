# Wave22 Build v3：Start 批准来源闭包与明确拒绝后的受控新草稿

## 最小修复

两次 T2 的专业 publication 在批准后进入各自 `BuildAuthorizationDecision.required_source_read_set`，不一定进入先前 assessment 或 current capability 的 reads。原 Start 只合并 assessment/cap/event，故即使两批准已保存，仍被服务器完整来源门槛拒绝。

v3 只在生成**未发送的新 Start 请求**时增加真实 GET 的两份 Current 批准闭包：按保存的 engineering/manufacturing Receipt subject_id+revision，在 `authorizations` 找唯一 row；其当前指针、role、Build、assessment ID/rev/SHA、approve/approved、is_current/source_status 须逐项一致。union 为固定 assessment + current cap + 当前 Start authority + 两批准完整 reads + 已保存 event 精确引用。版本冲突、>20 或缺失 Current 不裁剪、不猜来源。

无原 payload/数量/quote/发生钟/key 的改写。`start()` 的 `resume()` 仍先于任何新 GET/组装，已发送/preview_unknown 请求原封锁定；v3 不自动将服务器错误转换成可再预览的状态，不自动清除 checkpoint。

## 本次明确 409 的 Root 归档合同

只能由 Root 在实际已核对目标与身份的上下文执行以下受控步骤；本工具不把一个 error 字符串当作未保存证明，也没有新增客户端解锁接口。

1. 保存原 HTTP/API 原始错误证据：这是原完整 Start command 的 preview，明确收到 `409 MISSING_REQUIRED_EVIDENCE`，没有成功 preview/prepared token。无重定向、超时、断连、500 或无法识别的响应混入。
2. Root 对同一真实 product/actor/op、原 command ID/key 与语义，在明确核对的实际存续环境作只读核验：共同 direct/key/semantic replay 均无 Receipt，原请求无成功 Confirmation/审批凭证、无已消费 proof/开始事实/保留组或该请求 Audit/Outbox。若有任何已保存结果，先取原 Receipt，不能另起；若状态无法确定，仍 UNKNOWN，不能将本段作为猜测性绕过。
3. 在 0600 checkpoint 的 `rejected_requests` 列表原样追加拒绝归档（也可另存 0600 文件），原 `requests.start` 完整对象（original/body/key/readset/stage）、对应 HTTP 拒绝、核验范围/时点/无保存结论及原 command 摘要均保留，不能覆盖原 v2 请求或预览证据。Root 本次已提供 `start-explicit-rejection-readback-v1.json`：原 Start confirmations/receipts/build_starts 均为 0，完整 reads 5、原 provided 3；C 未执行该核验。只允许“明确拒绝且实际确认未保存”的这个特例，不把普通 VERSION_CONFLICT/其它 409 一概视为新草稿许可。
4. Root 明确决定将上述已拒绝的原 draft 从**活动 start 槽位**移到该归档；保留所有已保存 Receipts、`source-start` 的保存回执与完整原始请求、`events.start.raw/line/reference`。不得改旧 body/key/readset/发生钟，不改两批准/assessment 的历史。C 不执行这一 checkpoint 调整。
5. 应用 v3，然后使用**同一原始已发生 Start 材料**形成新 evidence-complete draft。新 draft 有独立 command/key 和当前 Product 水位，读集包含两 Current 批准 publication；这是真实拒绝后有证据的新请求，并非旧请求的重放或给 UNKNOWN 换 key。原事件资料不重新登记、不重造事件钟。
6. 新请求必须再次由服务器预览，人工一次确认，原封提交新的 prepared command。新 preview/execute 若未知立即保留该新请求原 key/body；原起点事件是否仍在有效窗口、>=两批准保存钟且不未来，以及当前职责/专业/来源/占用是否仍有效，仍由服务器实际核对。

没有明确绑定的“未保存”服务端/数据库证据时，禁止按第 4 步移出 UNKNOWN；保持原恢复路径，或交主线继续核对。两批准和新 source-start 已保存，只能证明这些独立动作，不证明 Start 已保存或必可开工。

## 定向检查与限制

实际 DTO 形状的纯回归验证两 Current 批准专属 publication（不在 assessment/cap reads 中）、当前 Start authority、event 来源全部进入 union，Start 方法保留原事件微秒字符串。负例覆盖 Current/role/assessment 漂移、重复/缺失批准、版本冲突、>20；旧 preview_unknown 通过实际 start() 入口仍阻止读取/重造/改 key。

同一 v3 候选 44 项无 DB/HTTP 纯检查通过（原 v2 38 + 新 6）0.717 秒，Ruff 与两文件 AST/compile 通过。记录在 check-result-v3.json 和 checks/pure-final-44.log；v1/v2 原文件/日志完整保留。测试只用真实 DTO 形状的内存替身，不是实际 Start/专业资格/完整 UOW 验收。C 不修改 Root 实际工具或 checkpoint，不连接 DB/HTTP；实际归档与重新预览/确认由 Root 执行。
