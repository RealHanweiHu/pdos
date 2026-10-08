# 可记录的安全局部减读前提（未实现）

Caller 显式传入 roots/reference 分离和实际 registry visited，能消除本次“无法知道哪些 ref 已完整覆盖”的结构障碍，但单独一个 visited identity集合不足以证明当前事实或Source可读。

最窄候选在 `owner._read` 的末次 binding：此时 initial registry、Source IO、terminal registry都已执行。caller可从本次具体terminal registry的实际owner读取结果确认 exact typed Issue/CAPA ref（kind/id/revision/key）确实已完整读取；对不在该集合内的supplementary references继续完整 `get_issue_for_change`。仅对已经由完整terminal owner验证的ref改为scope-only Current/ACL定位，随后仍执行原Project/caller/issuer/dependency/runtime/root-UOW/全部最早deadline末端guard。两遍registry及其事实/资格/Source读取保留。

如果只拥有首遍registry的visited，应继续保留terminal完整registry对同一 exact ref 的覆盖与材料比较，不能用首遍visited替代最后事实核验。第一个和第二个binding发生在首遍registry之前，尚无这种本次完整遍历证据，不能拿将来会读取或上相位结果作提前许可；最小局部候选可先只减末次binding的重复读取。

所需 provenance 应来自服务器当次具体registry的实际返回结果，并严格同Session/root+nested UOW/Context/caller/command、request roots/references、Current固定版、scope/audience、issue loader函数/配置、closure clock/runtime与期限。现有 `RegistryBasis` 不是通用授权 token，没有以上全部绑定；不得给函数新增可由任意caller声明的 `visited=set(...)` 或 `all_verified=True` 作为许可。私有同一调用词法范围传递与后续guard可以成为新的候选合同，须先做差异/漂移负例，而本次没有实现此扩展。

这里仍有一个重要顺序前提：scope-only helper之后如果还有可改变Source/资格的owner IO，同UOW/真实时钟/后置Source与资格守卫必须覆盖它；不能因terminal遍历此前刚通过就删掉最后guard。Project/Grant的pending拒绝、typed CAPA key的每distinct ref检查、当前完整来源读集和20/TTL上限保持。

预计是否减时、减多少，必须等待实际HTTP-worker profile与Root冻结的新候选测量。本次仅记录接口前提；现645-file PG候选未采用任何优化。
