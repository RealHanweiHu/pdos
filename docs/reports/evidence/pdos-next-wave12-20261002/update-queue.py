"""Update only the current queue after this checkpoint closes."""
import json
from pathlib import Path

r = Path(__file__).resolve().parent
root = r.parents[3]
check = json.loads((r / 'final-check.json').read_text())
assert check['result'] == 'passed_with_recorded_scope'
assert (r / 'result.md').exists()
p = root / 'tasks/ai-native-integrated-todo.md'
s = p.read_text()
lines = s.splitlines()
for index, line in enumerate(lines):
    if line.startswith('| G0 可信执行 |'):
        cells = line.split(' | ')
        cells[1] = '**部分实现，原件生命周期与专业/实物交接保护已汇合**：沿用第九至十一波安全、专业决定及原子开工守卫，第十二波接入具名实物状态、实际方法与部分接收。业务表增至 82 张，Agent 直接写权限为 0；联合选集最终 1,484 项通过（首轮 1,483 通过、1 条测试预期失败，仅修正测试后定向复验），0015 迁移往返/schema、构建和页面证据见[第十二波](../docs/reports/evidence/pdos-next-wave12-20261002/result.md)。'
        lines[index] = ' | '.join(cells)
    elif line.startswith('| G1 产品起点 |'):
        lines[index] = line.replace('实际品质交接仍待真实资格及执行端口。', '第十二波已接本地合成实物交样与品质部分接收；真实资格与正式开测端口仍未完成。')
    elif line.startswith('| G2 实物交接 |'):
        lines[index] = '| G2 实物交接 | **实物就绪、实际方法与品质部分接收闭环已接通**：复用实际配置/批次/样件及同一正式请求版本链，制造具名就绪/暂缓独立保存；交样 A/B 后只接收 A，B 保留暂缓、方法未知与下一责任人，数量 1/3、模穴 B/C 缺项如实保留。正式请求五版，浏览器将 B 方法续为 v2/unknown，A 接收范围及旧历史保持。运行代码冻结的联合选集最终 1,484 项通过，70 项界面辅助检查、四种布局与业务回读通过，见[第十二波](../docs/reports/evidence/pdos-next-wave12-20261002/result.md)。 | 下一步按[方案 §12](../docs/design/2026-10-02-pdos-next-execution-plan.md#12-已接收范围到实际开测的后续合同)接明确已接收范围、完整 Run/资源窗口、具名承诺与同事务实际开测。真实权威资格、统一测试占用/预约消费、TestRun、原值导入及专业复核仍未完成；本轮测试相关五个未来时钟为空，接收不授开测或外部交付资格。 |'
    elif line.startswith('| G4 制造交付 |'):
        lines[index] = line.replace('下一步接实物交接。', '第十二波已接实物交接与品质部分接收，下一步接测试承诺和实际开测。')
s = '\n'.join(lines) + '\n'
start = s.index('**2026-10-02 衔接与执行（本节续接）**')
end = s.index('**本轮条件**', start)
s = s[:start] + '''**2026-10-02 衔接与执行（本节续接）**：**第十二波实物就绪、实际方法与品质部分接收已完成本地合成验证**。实物状态、验证适配、办理界面三路独占并行；主线统一请求版本链、公共接线与验证。541 份源码/配置登记，运行代码冻结；主联合 1,483 通过、1 条错误码预期失败（975.8 秒），仅修正该测试并加强回滚断言，单例复验通过，最终选集 1,484 项通过；其后 24 项结构检查独立复验，不重复计数。0015 往返/schema、70 项界面辅助检查、最终生产构建、亮暗/两尺寸页面和旧历史回读通过；迁移前与闭环后备份保留。指定 57 份旧轨、25 份验证核心、7 份运行资产保持，82 张业务表 Agent 直接写权限 0、预览模型调用 0。[本轮完整证据](../docs/reports/evidence/pdos-next-wave12-20261002/result.md)；[第十一波检查点](../docs/reports/evidence/pdos-next-wave11-20261002/result.md)保留。原 N/P/Q 勾选与出口保持，未接入独立包不计主线可用。

**下一闭环（待施工）**：依[方案 §12](../docs/design/2026-10-02-pdos-next-execution-plan.md#12-已接收范围到实际开测的后续合同)接“已接收精确范围 → 固定 Run 与完整资源窗口 → 具名承诺 → 同事务占用并实际开测”。可并行测试资源/样件占用端口、Run 与请求推进适配、排程/承诺/开测界面；主线先固定 Run 和共享预约的原子关系，再划分文件归属，统一模型/迁移/角色与联合验证。复用现有验证及资源核，不另建样件/请求账本；本段仅登记下一施工入口，不宣称这些能力已实现。

''' + s[end:]
p.write_text(s)
print('Updated current queue to Wave12 evidence and next §12; historical N/P/Q sections retained.')
