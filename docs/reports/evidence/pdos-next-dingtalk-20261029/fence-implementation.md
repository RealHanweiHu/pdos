# G 发送 fence 修复 · 未编号独立 delta

基线是已实际安装843的 current live，仅4交付文件：guards.py小hook + 未编号SQL候选 + pure/PG各1测试文件。不要覆盖整个验证目录、不要改843或删除已有G数据。X2施工stage原样保留，未叠入此修复。

## 真实缺陷与最小修复

root实际同一service actor/session已证明：Binding与Application普通SELECT均可见、FOR UPDATE均不可见，reserve误将其当撤绑，Delivery.error_code=CANCELLED_RUN；证据复制在evidence/upstream-843-rls-diagnostic.json。两表runtime UPDATE policy仍只允许本人/管理员，本delta不放宽。

guards.message_binding(lock=True)先调用受限dingtalk_lock_message_binding(tenant,message)，然后普通RLS SELECT并populate_existing刷新；不是把helper当READ权限。helper从实际Message解析固定app/binding/owner，核实际tenant、actor=requester、该app真实active Agent service身份，按app→binding次序锁两行，等待app锁后再次核service身份，返回void，无DML/正文/计数。最终app/binding.active/epoch/owner/principal等仍由原普通guard逐项重核。

NOLOGIN maintenance仅增加两表UPDATE(id)列权限以满足PG行锁要求，不拥有表、不获active/owner/正文更新接口。原native revoke的Binding行锁与save_application的App行锁天然和helper串行；无需更改原命令或runtime RLS。发送仍持这两个行锁至实际transport及metadata提交；已先提交的撤绑/停用仍被刷新校验拒绝。普通读取lock=False不调helper、不加锁。

## 未编号SQL / wrapper

up.draft.sql与migrations/candidates/dingtalk_fence.py::SCHEMA_SQL严格相同，共9条；root先读实际head再分配下一真实号。前驱仅要求已843的G六表/维护role/metadata tenant policy/scope_actor/requester/dingtalk_service。新函数不存在时CREATE；不OR REPLACE未知旧函数。

由已获授权administrative migrator执行9条，exec_driver_sql(no_parameters=True)。两条UPDATE(id)只授maintenance；为ALTER OWNER短暂授maintenance public CREATE，创建函数后转给maintenance，随后显式恢复pdos_next_owner EXEC，撤PUBLIC/四runtime，必要runtime仅pdos_next_app EXEC（函数内再限定实际service actor）。最后撤maintenance CREATE，最终只有原USAGE。不要给runtime owner/maintenance成员或SET ROLE。无需ordinary_owner读业务数据；跨owner授权/转移以原843管理者能力执行，不在app连接上apply。

down.draft.sql/DOWNGRADE_SQL仅3条：DROP新函数→撤两项新增UPDATE(id)。没有新历史表、没有数据删除、无需回退843，既有Delivery/P26/unknown/nonce与counts保留；应用代码回退须和此helper移除协调。旧9个G函数、生命周期2函数与F/m3函数、角色、policy、FORCE RLS全部不改。

## 验证与root待执行

30定向pure通过（新5+原channel25），4文件AST/Ruff通过。16实际PG/Temporal仅collect，未执行DB/Temporal/出站，见pg-temporal-nodeids.json。

新增3项PG：真实synthetic transport持锁期间本人revoke/管理员disable的原HTTP命令必须等待，transport完成后命令提交；提交后旧Message再校验CANCELLED且send_count仍1。第三项复现service普通FOR UPDATE仍不可见而新helper成功，Human/错tenant调用42501、runtime精确EXEC、maintenance只有id UPDATE且无CREATE。测试只用原合成Adapter和原领域命令，不需要模型/真实钉钉。

原13项受影响名单完整列在JSON：原nonce(已过可保留无影响段)、ack+unknown恢复、两种撤绑、维护role、native Temporal、官方HTTP/丢响应/Temporal、跨品类retention与pending/quarantined及footprint。root决定分段复跑，不将collect当通过。新SQL实际编译、up/down/up、原历史counts/ACL与并发串行仍由root统一做。

本delta未改live/DB/843历史、不编正式号、不调用真实模型/凭据/出站。正式应用只按manifest的4文件逐项SHA核对；另有fence.patch等价review。
