# 待 root 实际执行：13 项 PG / Temporal

本包仅 collect，未运行 DB / Temporal。不得把 89 pure 或 MockTransport 当真实 PG 通过。实际测试仅显式 TEST_DATABASE_URL + 已核独立 pdos_test、实际四角色、显式本地 checkpoint/Temporal；不回退 .env。

先由 root 分配真实 head 的下一号、备份并核对 migration 权限/DDL/往返，再依次运行下面 13 项。fixture 使用原生本人身份、领域命令、实际 ModelTurn/Run、当前普通 RLS 与已注册 LangGraph；模型和钉钉端口为合成/MockTransport。测试文件源码已列在 integration manifest。

1. `tests/dingtalk/test_channel_pg.py::test_verified_binding_nonce_consume_no_unbound_run_and_one_to_one`
2. `tests/dingtalk/test_channel_pg.py::test_native_ack_and_unknown_delivery_recover_by_lookup_with_durable_p26`
3. `tests/dingtalk/test_channel_pg.py::test_actual_revoke_cancels_fixed_run_and_blocks_completion_without_owner_impersonation[owner]`
4. `tests/dingtalk/test_channel_pg.py::test_actual_revoke_cancels_fixed_run_and_blocks_completion_without_owner_impersonation[administrator]`
5. `tests/dingtalk/test_channel_pg.py::test_maintenance_role_is_metadata_only_and_has_no_runtime_membership`
6. `tests/dingtalk/test_channel_temporal_pg.py::test_same_xiaopai_native_run_private_answer_group_share_and_lost_receipt`
7. `tests/dingtalk/test_official_pg.py::test_official_binding_ingress_and_pending_receipt_use_actual_native_rows`
8. `tests/dingtalk/test_official_pg.py::test_official_lost_send_response_remains_unknown_without_second_send`
9. `tests/dingtalk/test_official_temporal_pg.py::test_official_wire_uses_same_temporal_graph_and_current_private_delivery`
10. `tests/dingtalk/test_retention_pg.py::test_private_two_category_delivery_retains_each_actual_root_without_service_body_read`
11. `tests/dingtalk/test_retention_pg.py::test_pending_original_blocks_new_body_copy_but_existing_receipt_metadata_can_update[pending]`
12. `tests/dingtalk/test_retention_pg.py::test_pending_original_blocks_new_body_copy_but_existing_receipt_metadata_can_update[quarantined]`
13. `tests/dingtalk/test_retention_pg.py::test_delivery_footprint_is_immutable_and_lifecycle_helpers_are_not_runtime_read_ports`

核心断言：本人 nonce 一次消耗、未绑定零 Run；原小Pai主图/Temporal → 私发 → 每次 P26 journal → pending/unknown 持久回执 → 重启查询而非重发；本人/管理员撤绑后取消实际原 Run 并阻止完成投递；维护角色无业务正文/运行时成员；官方收到 processQueryKey 仅受理，不冒充成功，无 key 丢响应保持 unknown；完整群成员未知时禁引文；跨两品类 private 原件 retention 元数据闭包和 clocks 完整，但 service 仍不能读原件正文；pending/quarantined 拒绝新副本而允许旧副本技术状态对账；固定 footprint/hash 不可改。

root 还需集成检查：真实 up/down/up；六表任一非空时 downgrade 在第一步拒绝且旧数据 counts 不变（不删测试历史绕过）；新/既有表 owner/ACL、所有维护函数真实 EXEC 与 owner flags；跨租户无影响；m3 保留快照引用/并发锁序；设置页本人绑定/撤绑/预览/回执/深链实际浏览器。Retention probe 仅 server metadata fixture，无真实发送，不表示 private customer 材料可以外发。真实钉钉账号/凭据/出站、真人验收与生产启用均未执行。
