# S1 集中回归的保留测试适配

以 `6e2120d` 的业务源码继续集中功能回归。修正五份旧测试：按当前接口保留上下文快照引用，内存会话补提案范围读取与状态事件写入，来源伪造断言对齐实际 `FORBIDDEN_SCOPE` 并核对失败零残留。原有读集、计算重验、本人确认和来源检查继续执行；本批未修改业务代码、迁移或前端。

| 验证 | 结果 | 原始记录 |
| --- | --- | --- |
| 绑定读取、品类采用、研究引用 | 159 通过 | [fixture-repairs-pure](fixture-repairs-pure) |
| 确定性计算证明 | 53 通过 | [deterministic-fixture-repairs](deterministic-fixture-repairs) |
| 实库来源范围与失败原子性 | 4 通过 | [scope-fixture-repairs](scope-fixture-repairs) |
| 五份改动的 Ruff | 通过 | [fixture-ruff-final.log](fixture-ruff-final.log) |

合计 **216 个不同病例**。实库仍为核对 marker 的独立 `127.0.0.1:64245/pdos_test`、head `s0_0772`，未回退 `.env`。

[首轮集中检查](backend-full-initial)在 5 失败、306 通过处停止；[第二轮](backend-full-fixed)发现 7 失败、675 通过后由主会话明确中止以收集明细，退出码 2，[停止原因](functional-stop.json)保留。上述失败均由本批适配处理，定向结果不能冒充完整回归通过。后续集中检查以独立日志记录，本文不提前声明其结果。

用户于 2026-10-17 明确暂跳性能验收，本轮未执行已准备的性能采样。原标准保留，暂缓不记为通过。无真实模型、KMS、业务外发、资格授予、golden-case 写入或生产操作。

另已按[官方价格页](https://platform.minimax.cn/docs/pricing/overview)补齐 MiniMax M3 的[公开人民币参考价](minimax-public-price-reference.json)与[未启用联验草案](../../../../runbooks/minimax-cn-m3-validation-draft.md)。账号实际计费、币种换算、凭据、协议范围及外发授权仍未获得；公开报价未写入运行配置。
