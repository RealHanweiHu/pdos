# 供给/成本独立组件首版

2026-10-02：交付 `SupplyEntry / SupplySnapshotHistory / CoverageShortages / CostBreakdown` 及 typed DTO/回调 port。供给来源服务器实质预览→一次确认→持久回执；不确定确认结果保留原凭据回查。快照、前后差异、全部占用和分项成本历史可读，未知不补零，已占用齐套与库存候选分开。

固定8份源码候选：`71350e7fb1127d4601e88ffacd4050b3c4c445553025793df7a5a6cc61c20e15`，逐文件摘要见 [candidate.json](candidate.json)。局部 TypeScript、包内 ESLint 通过；[15项合成组件/回调检查](checks.json)通过，含供方承诺日期与实际部分到货时间/关联的分开显示，原始输出见 [check.log](check.log)。空的 [typecheck.log](typecheck.log) 和 [lint.log](lint.log) 对应退出码0。backend read-model mapper与本包显示DTO逐字段核对无结构差异，消费摘要见 [consumed.json](consumed.json)。

只修改本组件目录和本 frontend 证据目录，无共享页面/API/BFF/样式/依赖变更。完整接口、接线步骤、消费摘要与未覆盖项见 [integration.md](integration.md)。正式持久接入、真实材料/资格、共同事务和浏览器联验由主线完成；本包首版不表示 G/N/P/Q 或正式人工出口完成。
