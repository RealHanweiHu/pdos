import test from "node:test";
import assert from "node:assert/strict";
import { localDatetime, matchMcpReceipt, mcpPendingKey, parseMcpPending, type McpCommand, type McpReceipt } from "./mcp-management";
const category = "00000000-0000-4000-8000-000000000001", principal = "00000000-0000-4000-8000-000000000002";
const command: McpCommand = { category_id: category, product_id: null, command_id: category, idempotency_key: category, operation: "mcp.connector.allow", expected_revision: 1, source_read_set: [], payload: { key: "synthetic", expected_revision: 0, endpoint: "https://synthetic.invalid/mcp", secret_ref: "synthetic-reference", tools: [], remove_tools: [], active: true, decision: "批准", reason: "本人合成准入", approval_token: "x".repeat(32) } };
const receipt: McpReceipt = { id: category, subject_id: category, subject_type: "mcp_connector", subject_revision: 1, operation: command.operation, category_id: category, writer_id: principal, requester_id: principal, agent_run_id: null, result: { key: "synthetic", active: true, tool_count: 0 } };
test("MCP recovery keeps exact category and named proof", () => {
  assert.deepEqual(parseMcpPending(JSON.stringify(command), category), command);
  assert.throws(() => parseMcpPending(JSON.stringify(command), principal));
  assert.notEqual(mcpPendingKey(principal, category), mcpPendingKey(category, principal));
  assert.throws(() => parseMcpPending(JSON.stringify({ ...command, payload: { ...command.payload, approval_token: "missing" } }), category));
});
test("only actual same-person connector receipt clears pending", () => {
  assert.ok(matchMcpReceipt(receipt, command, principal, category));
  for (const patch of [{ writer_id: category }, { subject_revision: 2 }, { category_id: principal }, { agent_run_id: category }, { result: { key: "other", active: true } }]) assert.equal(matchMcpReceipt({ ...receipt, ...patch }, command, principal, category), false);
});
test("tool grant recovery binds the exact grant id and explicit external-write choice", () => {
  const original: McpCommand = { ...command, operation: "mcp.tool.grant", payload: { connector_id: category, grant_id: principal, expected_revision: 0, connector_digest: "a".repeat(64), tool: "send", skill_key: "proposal_drafting", active: true, allow_external_write: true, expires_at: "2026-12-01T00:00:00Z", confirmation_token: "x".repeat(32) } };
  const actual = { ...receipt, operation: original.operation, subject_type: "mcp_tool_grant", subject_id: principal, result: { connector_id: category, tool: "send", skill_key: "proposal_drafting", active: true, allow_external_write: true } };
  assert.deepEqual(parseMcpPending(JSON.stringify(original), category), original);
  assert.ok(matchMcpReceipt(actual, original, principal, category));
  assert.equal(matchMcpReceipt({ ...actual, result: { ...actual.result, allow_external_write: false } }, original, principal, category), false);
  assert.equal(matchMcpReceipt({ ...actual, subject_id: category }, original, principal, category), false);
});
test("local datetime conversion preserves a valid date without inventing one", () => {
  const value = localDatetime("2026-12-01T12:30:00Z");
  assert.equal(new Date(value).toISOString(), "2026-12-01T12:30:00.000Z");
  assert.equal(localDatetime("invalid"), "");
});
