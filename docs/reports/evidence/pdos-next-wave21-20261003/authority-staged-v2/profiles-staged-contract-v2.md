# Wave21 专业与规则多范围配置 · 隔离暂存合同 v2

状态：隔离副本内实现并纯检查完成，尚未应用运行源码、启用新范围、连接数据库或授予真实资格。主线封存 Wave20 后仅应用下列两个运行文件与两个新测试。

## 服务器配置接口

- `professional_authority.service.configure_local_synthetic_profiles(engine, profiles, enabled=True)` 返回与列表顺序一致的 opaque `IssuerContext` tuple。`profiles` 必须为明确的 list、1～20项；每项字段为 `tenant_id/product_id/key/version`，可含 `project_id`。UUID对象及UUID字符串由本接口规范化为真实UUID；项目缺省或null保留原产品级签发合同。key/version沿旧合同至多100字符并规范空白。列表中key及完整scope各自唯一。
- 相同key/scope/nature/version的原配置复用原issuer对象和epoch，不撤回旧专业事实。plural遇不同scope、nature、version或坏epoch整批拒绝，不留下部分新登记，也不改变合成启用模式；其余scope/key保留。旧single配置接口仍可在同scope显式轮换版本/epoch；跨scope不能复用key。`configure_issuer`原真实模式仍禁用合成专业依据。
- 专业profile不是个人职责、资格或权限。合成模式必须由Root先核对测试环境marker，再从服务器配置调用。没有业务请求profile选择参数，不修改现专业事实、项目/原件ACL或私有规则。
- `capa_rule_publisher.configure_local_profiles(engine, profiles)` 返回 `ScopedRulePublisher`。每项沿原接口 exact `tenant_id/product_id/project_id/issuer_key/issuer_version`；UUID对象或字符串接受，key/version无首尾空白且至多100字符。仅list、1～20项，key及tenant/product分别唯一，项目必须明确UUID。
- 规则v1每个tenant/product只允许一个项目profile；同产品多个项目需要未来真实anchor派发协议，本波显式拒绝，不猜profile/最近配置/第一个选项。未知真实caller tenant/product为403；当前engine/dispatcher失配或签发人撤回拒绝。read按实际ctx+产品唯一选，再由原Registered读取真实固定候选anchor并核其项目和原来源。
- 规则plural相同原key/scope/version复用原Issuer；不同scope或version拒绝。single保持原 `RegisteredSyntheticRulePublisher` 返回类型，并保留同scope显式版本轮换；独立单调issuer epoch表使移除后再配置不能回到旧epoch。
- 规则marker验证沿原 `verify_test_target(engine)`，整批校验完才验证并登记。配置失败时现registry/epoch/dispatcher原样保持。Root公共single与plural参数互斥由Root API/ASGI落实，未在本包发明另一套公共配置入口。

## 实际运行时边界

ScopedRulePublisher `.read` 与 `.current` 均在delegate结束后重新核对所选publisher、真实engine/dispatcher身份和全registry stamp。read另在所有delegate读取后用fresh真实UTC钟核返回截止时间。

`.epoch` 为固定排序的运行时SHA，绑定配置epoch、当前dispatcher身份、完整实际issuer scope/version/身份/epoch及单调epoch账。现 `ActualFactOwner.runtime_stamp` 已取publisher identity/epoch及真实issuer registry，无需本包修改。此SHA、dispatcher、caller、live资格、scope选择不会写入publication body；返回实际delegate原材料，不造新事实。原件/source/anchor/专业/政策/消费/UOW/最后Current和SQL守卫由现实际owner继续核对。

## 应用文件（仅四个）

| 暂存路径（相对本目录） | Root目标（相对pdos-next） |
|---|---|
| pdos_next/domain/professional_authority/service.py | server/pdos_next/domain/professional_authority/service.py |
| pdos_next/capa_rule_publisher.py | server/pdos_next/capa_rule_publisher.py |
| tests/professional_authority/test_profiles.py | server/tests/professional_authority/test_profiles.py |
| tests/capa_effectiveness/test_rule_publisher_profiles.py | server/tests/capa_effectiveness/test_rule_publisher_profiles.py |

本目录复制了310份纯Python源码，没有symlink；其余308份未改。不迁入整份暂存副本、不改任何数据库/迁移/公共API/Web/依赖。Root应用前核两个目标基线SHA与source-manifest-v2.json。真实两个测试目标尚不存在。

## 检查与限度

- 最终新增纯检查62项通过（1.24秒）；原专业评估/原值核验接口受影响兼容纯检查57项通过（1.61秒），两个范围分别记录，不能相加成公共联合验收。
- 四个owned文件Ruff与format-check退出0；4 AST及2个实际暂存模块import通过，模块路径确认在本隔离目录。
- marker及delegate成功用例明确采用替身，只核配置/派发/末端撤回/时点边界；不能证明真实marker、来源ACL、原件、专业资格、实际发布、数据库原子组或生产启用。所有运行测试均 `--noconftest`，未连接数据库、HTTP或浏览器。
- 首轮53项与中间57项旧日志及最初格式问题原日志保留；最终v2按Root收紧仅list、版本冲突整批拒绝、current末端重核。精确命令、各源/日志SHA在manifest。
