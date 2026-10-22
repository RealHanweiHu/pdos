# 预览原命令时钟等价修复 v2

主线实际页面 inputs/preview 均为 200；共同预览按 typed payload 序列化，把原观察范围的 `+00:00` 规范为同一时点的 `Z`。原 `sameFactCommand` 比较 tokenless payload 的字面时间字符串，导致前端误拒预览。

仅修改这一个函数：外层 command/key/product/revision/operation/完整读集仍逐值严格相等，payload 使用既有 `sameFactPayloadSemantics`。该函数仅允许 observed_from、observed_until、at.occurred_at、records[*].occurred_at 四类已声明时钟以同微秒瞬时等价，原值、原来源、quote hash、原时区、数组顺序及所有其他字段保持严格比较。没有重新格式化实际值或四舍五入。返回的 prepared command 原封保留用于提交及恢复。

添加实际范围 `+00:00→Z` 通过、保持原返回命令的恢复检查，以及差一微秒/来源对象/quote hash/数字或原数字字面/外层读集变化均拒绝的检查。当前 24 helper 全过、定向 TS 退出 0、四文件 ESLint 0 错误 0 警告。manifest v2 列出全部四文件 SHA，实际差异仅 contract/test 两份；v1 及原实际通过记录均保留，不累计。

此次未修改 component/state、共享服务或 BFF，未执行 HTTP/数据库/浏览器/公共构建。后续主线将重新构建并按原 pending 请求预览。离线工具目前明确绑定 v1 manifest，若核 v2 源需主线授权改为明确 v2 绑定，不能自动忽略源差异。
