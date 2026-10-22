# 独立 UI 验证

独占 `change_control/` 候选通过局部 TypeScript noEmit（incremental=false）、ESLint（--no-cache）和 22 个 node 合成组件/候选边界检查。原始输出为 `ui-typecheck.log`、`ui-eslint.log`、`ui-component-checks.log`。

覆盖固定双线路径/出处、缺制造边 UNKNOWN、AI推测分栏、批准/实施故障/部分生效/独立复核/关闭分离、缺port/未注册、AI只准备T2候选、未知或缺完整回执锁新动作、source/configuration漂移、跨范围引用拒绝、固定来源/受众不足、自批/降级拒绝、所有者固定实施事实、未核验/越范围回执、全范围独立复核、执行者自证拒绝、关闭独立动作、无效决定历史、UNKNOWN对象处置、精确新根修订、原始units/dispositions完整透传、影响缺边/来源/覆盖UNKNOWN拒绝准备批准及 sent/accepted 不冒充生效。

命令在 `pdos-next/web` 运行，仅包括 `tsc --project src/components/change_control/tsconfig.check.json --noEmit --incremental false`、`eslint src/components/change_control --no-cache`、`node --test src/components/change_control/render.test.mjs`。测试使用内存TSX编译和静态组件渲染；不启动服务、不写共享.next、不安装依赖、不读取.env/.local/凭据、不连接数据库或外部服务。合成数据不导出给业务页面。

未覆盖真实数据库事务/HTTP/BFF/浏览器交互、亮暗、多尺寸、来源ACL/实际资格和正式出口。结果只属于 `ui-candidate.json` 的包内固定文件版本。
