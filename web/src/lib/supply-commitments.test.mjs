import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json")), ts = dependency("typescript");
const filename = path.join(directory, "supply-commitments.ts"), loaded = new Module(filename);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const { blankPromise, createCommand, reviseCommand, closeCommand, reopenCommand, quantityText, actualText, canMaintain, checkBoard } = loaded.exports;

const product = { id: "p1", revision: 3 }, build = { id: "b1", revision: 2, owner_id: "owner" };
const draft = { ...blankPromise(), materialId: "m1", supplierRef: " ACME-01 ", quantity: "30", unit: "ea", promisedLocal: "2026-11-20T09:00", text: "供方说 20 日前交 30 台", statement: "电话确认" };
const item = { commitment_id: "c1", revision: 2, body: { responsible_id: "me" } };

test("create carries the fixed Build, the zone and the person's own statement as T0", () => {
  const command = createCommand(draft, build, product, "Asia/Shanghai");
  assert.equal(command.operation, "supply.commitment.record");
  assert.deepEqual(command.source_read_set, []);
  assert.equal(command.expected_revision, 3);
  assert.equal(command.payload.statement, "电话确认");
  assert.equal(command.payload.record.supplier_ref, "ACME-01");
  assert.equal(command.payload.record.expected_build_revision, 2);
  assert.equal(command.payload.record.original_timezone, "Asia/Shanghai");
  assert.match(command.payload.record.promised_at, /^2026-11-\d\dT\d\d:00:00\.000Z$/);
  assert.equal("confirmation_token" in command.payload, false);
});

test("unknown stays unknown and missing basis or unit is refused before sending", () => {
  const unknown = createCommand({ ...draft, quantity: "", unit: "", promisedLocal: "" }, build, product, "UTC");
  assert.equal(unknown.payload.record.quantity, null);
  assert.equal(unknown.payload.record.promised_at, null);
  assert.throws(() => createCommand({ ...draft, statement: " " }, build, product), /依据/);
  assert.throws(() => createCommand({ ...draft, unit: "" }, build, product), /单位/);
  assert.throws(() => createCommand({ ...draft, quantity: "-1" }, build, product), /非负/);
  assert.throws(() => createCommand({ ...draft, materialId: "" }, build, product), /物料/);
});

test("follow-up commands bind the exact current version", () => {
  assert.deepEqual(reviseCommand(item, draft, product, "UTC").payload.commitment, { id: "c1", revision: 2 });
  assert.equal(closeCommand(item, "已到货", "快照已登记", product).payload.record.action, "close");
  assert.throws(() => closeCommand(item, "", "x", product), /关闭原因/);
  const reopen = reopenCommand(item, "余量未到", "仍需跟进", product);
  assert.equal(reopen.payload.reason, "余量未到");
  assert.throws(() => reopenCommand(item, "", "x", product), /原因/);
});

test("display never adds commitments to stock and shows unknown quantities", () => {
  assert.equal(quantityText("30.00000000", "ea"), "30 ea");
  assert.equal(quantityText(null, "ea"), "数量未知");
  assert.equal(actualText({}), "尚无记录");
  assert.equal(actualText({ ea: "6", unknown: 1 }), "6 ea；1 条数量未知");
  assert.equal(canMaintain(item, "me", build), true);
  assert.equal(canMaintain(item, "owner", build), true);
  assert.equal(canMaintain(item, "stranger", build, "lead"), false);
  assert.throws(() => checkBoard({ build: { id: "other" }, lines: [], commitments: [], kit_rule: "" }, "b1"));
});
