# 资源资格与预约独立包 · 交付结果

2026-10-02。本包授权范围已实现并完成适当局部验证。候选SHA-256：`b0172186bb50df62f85e99365cde18555e6f781a084406a6c7f5e7bfc2e1bed5`；18份源码、测试、组件及接入/复核资产见 [candidate-manifest.json](candidate-manifest.json)。唯一清单与其他包未改动。

## 已实现

- 封闭不可变DTO：设备/治具/人员/线体/模具固定身份与版本、用途/工序、已有具名验收/校准/资格及有效期、维护事实、当前日历/TZif/容量、正式预约及释放取消历史。
- 确定性准备度：UNKNOWN/BLOCKED/READY_WITH_CONDITIONS/READY；硬阻塞保留并优先于未知，完整执行区间资格覆盖、限定条件/到期、固定版本/适用性、授权撤销、维护和来源撤回重核。容量checked单独表示，不当作资格或占用。
- 预约handler与服务端事实ports：只读实质预览、暂定记录、正式预约暂存、释放/取消与执行前重核；半开UTC区间、原IANA时区、固定日历和23/25小时DST日、有界Decimal容量扫线、稳定run意图幂等、版本及occupancy CAS合同。重放不重复确认/占用，终态不静默复活。
- 可供既有 `verification.SampleAvailabilityPort.reserve` 消费的资源子协议；全部在调用者UOW，返回明确“暂存”结果，不commit、不创建SampleUnit或实物消费权威。服务器已核验真实Actual事件可随既有RunStart办理，预约时间不会自动填Actual。
- 独立资源组件及typed props/callback：资格有效期、未知/冲突/限定条件、固定资源范围、暂定/正式/释放/取消历史与独立接收/Actual事件；现有Button/语义主题，候选只委托主线共同预览和具名决定。共同确认/回执通过slot注入，无第二套确认或命令。

后端入口：`pdos-next/server/pdos_next/domain/resource_readiness/handlers.py`。组件入口：`pdos-next/web/src/components/resource_readiness/index.ts`。详细接线与限制见 [integration.md](integration.md) 和 [组件映射说明](../../../../pdos-next/web/src/components/resource_readiness/integration.md)。

## 验证与固定接口

[checks.json](checks.json) 保存六项原始命令与退出码，最终全部为0：

| 检查 | 覆盖与结果 |
|---|---|
| 独占pytest | **109项通过**；设备/治具/人员及crew资格、全区间有效期、条件与失效、固定身份/来源/授权漂移、半开容量扫线、DST、稳定意图重放、过期/修改预览、释放取消历史、现行正式占用完整性、并发合成竞争、一笔UOW多失败点回滚；[原始输出](pytest.log) |
| Ruff / format | 包内10份Python检查通过，零独立connection/commit/rollback；[Ruff](ruff.log)、[格式](format.log)、[导入边界](import-boundary.json) |
| 局部TypeScript / ESLint | nonincremental/noEmit和--no-cache通过，仅独占组件；[TypeScript](typecheck.log)、[ESLint](eslint.log) |
| 组件/守卫 | **10项通过**；真实React SSR、缺port/未注册/漂移/未知回执失能、T2禁AI、资格全区间与四类事实展示、共同确认slot；[原始输出](components.log) |

后端用 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`、`PYTHONDONTWRITEBYTECODE=1`、独占 `--confcutdir`、`-p no:cacheprovider`，未加载数据库fixture。复核脚本 [verify.py](verify.py) 只运行本包纯检查，可用 `--only` 局部重核。修复一次合成输入中calendar/source不成对和断言忽略硬阻塞优先的测试问题，以及一处端口文档长行；原始失败输出保存在 [首次pytest](pytest-first-attempt.log)、[首次静态记录](checks-first-attempt.json)、[首次Ruff](ruff-first-attempt.log)。没有隐藏未通过检查。

消费 `verification/ports.py`、`schemas/verification/contracts.py`、规划日历DTO/WorkingTime及已有Button，交付前与初始摘要复核：**零接口漂移**，见 [初始消费](consumption-initial.json)、[最终消费](consumption-final.json)、[前端消费摘要](ui-consumption-final.json)。接口未修改。

## 事务与失败恢复

主线必须一个调用者Session，按统一父Request→Run→稳定意图→资源UUID→样件UUID锁序，跨项目完整占用读取，资源/资格/日历/原件/权限epoch与预约CAS一起核验。资源暂存、实际样件预约/破坏性消费、共同证明、Request/Run、回执/审计/Outbox一起提交或一起回滚；复用外层已消费且绑定资源读集的证明，不再确认一次。结果未知先查原意图回执。

合成检查覆盖资源后样件失败、样件后资源失败、回执后失败、CAS及资源暂存后失败的整笔回滚。另有明确反例证明拆成两笔UOW会留下孤立资源占用。模拟UOW采用内存事务与互斥锁，线程竞争只证明该合成编排中的单赢家；**不能代替PostgreSQL锁/CAS、RLS或跨资源样件真实事务验收**。

## 未接线、主线余项与阻塞条件

公共models/迁移/注册/RLS/API/BFF/父页面、资源事实与ReservationStore的调用者Session持久适配、品质reserve实际资源+样件接线、真实资格/资源/维护/日历、共同政策及证明绑定均由主线接入。未运行数据库/迁移/HTTP/实际浏览器、亮暗尺寸整链、共享构建、真实模型/原件/外发/云/生产，也没有git commit/push或读取.env/.local/真实密钥。

具名治具验收沿 `npi.fixture.accept` T2；人员资格签发/撤销、校准接受、维护及独立预约/释放取消动作需专用政策注册。未注册动作保持待接入，缺真实条件保持UNKNOWN，不授真实资格、不开放T0/AI T2、不宣称G/N/P/Q或人工Exit通过。本包已可调用；真实业务使用须完成上述主线接线与公共联合验证。
