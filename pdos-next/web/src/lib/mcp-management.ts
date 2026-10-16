export type McpTool = { binding_digest?: string; name: string; description: string; kind: "read" | "write"; input_schema: Record<string, unknown>; output_schema?: Record<string, unknown> };
export type McpConnector = { id: string; key: string; revision: number; active: boolean; tool_count: number; receipt_id: string | null; endpoint?: string; credential_reference_set?: boolean; binding_digest?: string };
export type McpIndex = { items: McpConnector[]; can_edit: boolean; category_revision: number; next_cursor: string | null };
export type McpGrant = { id: string; tool: string; skill_key: string | null; automation_rule_id: string | null; revision: number; active: boolean; expires_at: string; allow_external_write: boolean; authorized_by_name: string | null; receipt_id: string | null; state: "active" | "revoked" | "expired" | "connector_inactive" | "stale" };
export type McpDetail = { connector: McpConnector; tools: McpTool[]; grants: McpGrant[]; next_tool_cursor: string | null; next_grant_cursor: string | null; category_revision: number; as_of: string };
export type McpHistory = { items: { id: string; operation: string; subject_id: string; revision: number; decided_by_name: string | null; reason: string; receipt_id: string; created_at: string }[]; next_cursor: string | null };
export type ConnectorPayload = { key: string; expected_revision: number; endpoint?: string | null; secret_ref?: string | null; tools: McpTool[]; remove_tools: string[]; active: boolean; decision: "批准"; reason: string; approval_token?: string };
export type GrantPayload = { connector_id: string; grant_id: string; expected_revision: number; connector_digest?: string | null; tool: string; skill_key: string; active: boolean; expires_at?: string | null; allow_external_write: boolean; confirmation_token?: string };
export type McpCommand = { category_id: string; product_id: null; command_id: string; idempotency_key: string; expected_revision: number; source_read_set: [] } & ({ operation: "mcp.connector.allow"; payload: ConnectorPayload } | { operation: "mcp.tool.grant"; payload: GrantPayload });
export type McpReceipt = { id: string; subject_id: string; subject_type: string; subject_revision: number; operation: string; category_id: string; writer_id: string; requester_id: string; agent_run_id: string | null; result: { key?: string; connector_id?: string; tool?: string; skill_key?: string; active: boolean; tool_count?: number; allow_external_write?: boolean } };
export type McpPreview = { command: McpCommand; expires_at: string | null; write_tier?: "T2"; review: { key: string; endpoint?: string; active: boolean; next_revision: number; effect: string; tool_count?: number; upsert_tools?: McpTool[]; remove_tools?: string[]; binding_changed?: boolean; credential_reference?: string; credential_availability?: string; reason?: string; tool?: string; skill_key?: string; tool_kind?: string | null; allow_external_write?: boolean; expires_at?: string } };
export const mcpStates = { active: "当前有效", revoked: "已撤销", expired: "已到期", connector_inactive: "连接器已停用", stale: "目标或工具结构已变，须重新确认" };
export const mcpPendingKey = (principal: string, category: string) => `pdos-mcp-management:v1:${principal}:${category}`;
export function parseMcpPending(raw: string, category: string): McpCommand {
  const value = JSON.parse(raw) as McpCommand;
  const uuid = (v: unknown) => typeof v === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(v);
  const revision = (v: unknown) => Number.isSafeInteger(v) && (v as number) >= 0;
  const keys = ["category_id", "product_id", "command_id", "idempotency_key", "operation", "expected_revision", "source_read_set", "payload"];
  if (!value || Object.keys(value).length !== keys.length || Object.keys(value).some(key => !keys.includes(key)) || value.category_id !== category || value.product_id !== null || !uuid(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160 || !revision(value.expected_revision) || value.expected_revision < 1 || !Array.isArray(value.source_read_set) || value.source_read_set.length || !value.payload || !revision(value.payload.expected_revision) || typeof value.payload.active !== "boolean") throw new Error("原 MCP 请求无法读取，请保留恢复记录并核对当前登记。");
  const p = value.payload;
  if (value.operation === "mcp.connector.allow") {
    const p = value.payload;
    if (typeof p.key !== "string" || !p.key || p.key.length > 160 || p.decision !== "批准" || typeof p.reason !== "string" || !p.reason.trim() || !Array.isArray(p.tools) || p.tools.length > 50 || !Array.isArray(p.remove_tools) || p.remove_tools.length > 50 || typeof p.approval_token !== "string" || p.approval_token.length < 20 || p.approval_token.length > 128) throw new Error("原 MCP 具名登记证明不完整。");
  } else if (value.operation === "mcp.tool.grant") {
    const p = value.payload;
    if (!uuid(p.connector_id) || !uuid(p.grant_id) || typeof p.tool !== "string" || !p.tool || p.tool.length > 160 || typeof p.skill_key !== "string" || !p.skill_key || p.skill_key.length > 160 || typeof p.allow_external_write !== "boolean" || typeof p.confirmation_token !== "string" || p.confirmation_token.length < 20 || p.confirmation_token.length > 128 || p.active && (typeof p.connector_digest !== "string" || !/^[a-f0-9]{64}$/.test(p.connector_digest) || typeof p.expires_at !== "string" || !Number.isFinite(Date.parse(p.expires_at)))) throw new Error("原 MCP 工具授权证明不完整。");
  } else throw new Error("原请求不属于 MCP 登记或授权。");
  if (Object.prototype.hasOwnProperty.call(p, "tenant_id") || Object.prototype.hasOwnProperty.call(p, "actor_id")) throw new Error("原 MCP 请求包含无效身份范围。");
  return value;
}
export function matchMcpReceipt(receipt: McpReceipt, original: McpCommand, principal: string, category: string) {
  if (receipt.operation !== original.operation || receipt.category_id !== category || receipt.writer_id !== principal || receipt.requester_id !== principal || receipt.agent_run_id !== null || receipt.subject_revision !== original.payload.expected_revision + 1 || receipt.result?.active !== original.payload.active) return false;
  return original.operation === "mcp.connector.allow" ? receipt.subject_type === "mcp_connector" && receipt.result.key === original.payload.key : receipt.subject_type === "mcp_tool_grant" && receipt.subject_id === original.payload.grant_id && receipt.result.connector_id === original.payload.connector_id && receipt.result.tool === original.payload.tool && receipt.result.skill_key === original.payload.skill_key && (!original.payload.active || receipt.result.allow_external_write === original.payload.allow_external_write);
}
export function localDatetime(instant: string) {
  const date = new Date(instant), shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return Number.isFinite(shifted.getTime()) ? shifted.toISOString().slice(0, 16) : "";
}
