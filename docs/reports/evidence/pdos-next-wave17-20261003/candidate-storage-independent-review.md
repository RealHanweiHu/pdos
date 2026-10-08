# Wave17 候选完整登记读取：独立只读复核

结论：在本次冻结三文件的限定范围内，未发现需要窄修的明确阻塞。它可以提供实际持久行与共同组的完整、可重复核对引用；不能作为候选当前适用、专业资格、原件安全或同事务消费的肯定证明。本次没有运行测试、数据库、HTTP、浏览器或公共检查，也未修改实现与测试文件。

## 读取版本

| 文件（`pdos-next/staging/wave17/`） | SHA-256 |
| --- | --- |
| `candidate_storage.py` | `2f23a27435fd77092676c13ef7c4c052fcec01d2ce7c5f92b0a844d3398d388c` |
| `test_candidate_storage.py` | `3aaeeadd5f6b5c537e6bd58314b8b4cd69345537fb241201111d993d6a97aa07` |
| `candidate-storage-contract.md` | `ac3c89e55a0115f6d5b8d2ed9ea11d5b6b6ee8c88bff3fe421d9006f5b85e4b7` |

三项哈希与 A 的最终冻结通知逐值一致。A 报告其所属离线检查为 53 项通过、3.18 秒；该结果属于 A 的替身 SELECT／无连接实际 Session 检查，不是本报告执行的验证，也不是 PostgreSQL、原件或专业办理验收。

## 核对结果

- **完整引用没有被旧摘要替代。** `candidate_storage.py:133` 遍历实际 ORM 全部列；`:389` 保存实际 Receipt、Audit、Confirmation 全列及 Outbox 非投递列；`:468` 使用冻结的 `pdos-capa-candidate-full-v1` 公式生成完整引用。仅排除五项投递状态与后来 RequestKey 别名，原请求摘要及实际原关联仍核对。Receipt 的展平结果只含 binding／inspection 摘要，未加入会自引用的完整摘要。
- **原锚与范围没有被 Current 或 peer Grant 替换。** `:233` 比较真实 origin 整个 DTO；`:268` 从实际原 Issue 完整聚合重建 basis；`:303` 核原锚、basis、inspection 和行读集的完整闭包，沿既有规范限制来源总量。候选私人受众与实际 Project 分别检查；历史原版仍需要独立谱系 owner，不能因最新 Issue 可读而获得办理资格。
- **语义 owner 缺失明确拒绝。** `:48` 要求服务器注入实际 module、严格 Payload 及同一 semantic callback；`:159` 按真实 Payload 重解析无 token 保存语义。缺 owner 为 503，不借用 Link 语义或任意 JSON identity。当前并无公共 Candidate Payload；测试的 `TestOnlyPayload` 不能作为未来注册合同。
- **保存时钟和末端检查没有续期。** `:434` 核原 proof 首消费钟与行保存钟的历史区间，使用原 proof Product revision；现在过期不抹去已保存历史。JSON 中原 ISO／时区字符串和原可省略键保留，列 datetime 只作带微秒的 aware UTC 规范。`:481–:512` 完整重读原行、共同组、origin 与 Project 后，再查调用者／Grant、核 module callback 和实际 UOW，并采集新的读取时钟；末端查询期间撤回或跨过权限时效不能沿用早先肯定结果。历史 consumed=True 没有被声称为本事务 false→true 证明。
- **输出保持保守。** `:90` 与 `:536` 固定所有 live 授权／字节／原失败／同 UOW 消费声明为 False，明确列出缺失的七 owner 门禁；保存的 `CandidateInspect.current` 只是历史材料。`candidate_owner` 返回原始 registry 读取字段，不安装公共消费器，也不默认提高 UI capability。

## 后续接线仍必须保留

实际候选 writer／Payload 与 semantic owner 要先冻结并从服务器显式注入；实际 false→true 消费、完整原子组写入与 SQL 反向配对另行验证。当前读取没有取得 child Link 的完整 owner 证明，也没有重读原件字节、安全 epoch、参与者独立性、当前政策／issuer 或七个 live owner。全列摘要只能固定已保存材料，不能代替这些门禁。

实际 PostgreSQL／RLS／触发器及跨连接并发仍待宿主联验；此读取不持写锁，不宣称整个多次 SELECT 已成为一次数据库一致性或生产资格证明。候选、观察、具名 Review、有效性与关闭操作的公开授权仍由未来明确宿主合同办理。
