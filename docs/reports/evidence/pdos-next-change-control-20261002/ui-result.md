# 独立 UI 首版结果

已实现 ChangeControlWorkbench、ChangeControlReading、ChangeImpactReading、ChangeEffectivityReading；受控 draft/callback 与封闭 ChangeIntent，所有来源与身份由父服务器投影提供。双线有出处路径、AI猜测、UNKNOWN分栏；审批、实施失败/未知、实际生效、独立复核、具名关闭分离；新对象只作受控意图与固定引用。实际实施/生效/复核只取所有者已核验 item/fact ID。精确生效units及逐对象dispositions原样保留，UNKNOWN处置阻止批准。

共同预览由父传入，组件没有确认执行器/业务存储。来源或配置漂移、部分范围、未知回执、自批与执行者独立自证等边界通过局部检查。22项合成检查、noEmit非incremental TypeScript、ESLint无cache全部通过，原始输出和范围见 [ui-checks.md](ui-checks.md)。

固定源码候选为 `6552e1e750dc3e8cc26dcdb88d8684c3ef2aba52ba8002cbf6986b020eaa5bc6`，逐文件哈希见 [ui-candidate.json](ui-candidate.json)。初始/最终既有消费接口哈希相同，未发现 Button/共同预览参考接口漂移；同期父后台 DTO最终读取摘要单列 ui-backend-interface-final.json，主线汇合时再次复核。

未接父页面/BFF/registry/迁移/RLS、真实GraphSnapshot和plan/fact来源、资格/权限/currentness、共同确认/T2 proof/回执恢复。主线接线、同Session事务失败回滚/幂等及公共联合验证见 [ui-integration.md](ui-integration.md)。未验证数据库、HTTP、真实浏览器、真实材料或G/N/P/Q出口；不把模块合成检查当正式验收。
