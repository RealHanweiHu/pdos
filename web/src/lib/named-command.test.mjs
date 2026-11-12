import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json")), ts = dependency("typescript");
const filename = path.join(directory, "named-command.ts"), loaded = new Module(filename);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const { makeCommand, preparedCommand, validReceipt, previewCommand, submitPrepared } = loaded.exports;

const product = { id: "p1", revision: 4 };
const echo = (command, extra) => ({ command: { ...command, payload: { ...command.payload, ...extra } }, review: { effect: "只登记。" } });

test("a command carries the product revision and a fresh identity", () => {
  const one = makeCommand(product, "npi.tooltrial.create", { a: 1 }), two = makeCommand(product, "npi.tooltrial.create", { a: 1 });
  assert.equal(one.expected_revision, 4); assert.notEqual(one.command_id, two.command_id);
  assert.ok(one.idempotency_key.startsWith("npi.tooltrial.create:"));
});

test("T1 needs the confirmation token, T2 the named approval flags", () => {
  const command = makeCommand(product, "x.y", {});
  assert.ok(preparedCommand({ ...echo(command, { confirmation_token: "t" }), expires_at: null }, command, "T1"));
  assert.equal(preparedCommand(echo(command, {}), command, "T1"), null);
  assert.equal(preparedCommand(echo(command, { approval_token: "t" }), command, "T2"), null);
  assert.ok(preparedCommand({ ...echo(command, { approval_token: "t" }), write_tier: "T2", named_decision: true, expires_at: null }, command, "T2"));
  assert.equal(preparedCommand({ ...echo(command, { confirmation_token: "t" }), write_tier: "T2" }, command, "T1"), null);
});

test("a preview for another command or an expired preview is refused", () => {
  const command = makeCommand(product, "x.y", {}), other = makeCommand(product, "x.y", {});
  assert.equal(preparedCommand(echo(other, { confirmation_token: "t" }), command, "T1"), null);
  assert.equal(preparedCommand({ ...echo(command, { confirmation_token: "t" }), expires_at: "2000-01-01T00:00:00Z" }, command, "T1"), null);
});

test("receipts must match the operation and subject type", async () => {
  const command = makeCommand(product, "x.y", {});
  const receipt = { id: "00000000-0000-4000-8000-000000000001", subject_id: "00000000-0000-4000-8000-000000000002", subject_revision: 1, operation: "x.y", subject_type: "tool_trial" };
  assert.ok(validReceipt(receipt, command, "tool_trial")); assert.ok(!validReceipt(receipt, command, "other"));
  const calls = [];
  const api = async (pathName, body) => { calls.push(pathName); return pathName.endsWith("preview") ? { ...echo(body, { confirmation_token: "t" }), expires_at: null } : receipt; };
  const prepared = await previewCommand(api, command, "T1");
  assert.deepEqual(await submitPrepared(api, prepared, "tool_trial"), receipt);
  assert.deepEqual(calls, ["v1/commands/preview", "v1/commands"]);
  await assert.rejects(submitPrepared(api, prepared, "other"));
});
