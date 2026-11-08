import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json")), ts = dependency("typescript");
const filename = path.join(directory, "project-team.ts"), loaded = new Module(filename);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const { roleChanges, selectableRoles, needsGrant, grantLabel, leadHolder, teamRequest, teamPath, pendingText } = loaded.exports;

const owner = "00000000-0000-4000-8000-000000000001", peer = "00000000-0000-4000-8000-000000000002", third = "00000000-0000-4000-8000-000000000003";
const member = (principal_id, roles) => ({ member_id: `m-${principal_id}`, principal_id, name: principal_id.slice(-1), is_owner: principal_id === owner, roles, joined_at: "2026-11-07T00:00:00Z", added_by: owner, added_by_name: "负责人", grant: "write", active_person: true });
const view = {
  project: { id: "p", name: "合成项目", owner_id: owner, owner_name: "负责人", visibility: "private" }, revision: 4, can_manage: true, membership_controls_visibility: true,
  catalog: { revision: 2, default: false, roles: [{ key: "mechanical", name: "结构", active: true }, { key: "quality", name: "品质", active: true }, { key: "battery_safety", name: "电池安全", active: false }] },
  members: [member(owner, []), member(peer, [{ key: "mechanical", name: "结构", lead: true }, { key: "quality", name: "品质", lead: false }]), member(third, [{ key: "battery_safety", name: "电池安全", lead: false }])],
  departed: [], vacant_roles: [], roles_without_lead: ["quality"],
};

test("taking a lead moves it in the same change set and keeps the previous holder's role", () => {
  const changes = roleChanges(view, owner, [{ key: "mechanical", lead: true }]);
  assert.deepEqual(changes, [
    { action: "set_roles", principal_id: owner, roles: [{ key: "mechanical", lead: true }] },
    { action: "set_roles", principal_id: peer, roles: [{ key: "mechanical", lead: false }, { key: "quality", lead: false }] },
  ]);
  assert.equal(leadHolder(view, owner, "mechanical")?.principal_id, peer);
  assert.equal(leadHolder(view, peer, "mechanical"), undefined);
  // No lead taken: only the edited member changes.
  assert.equal(roleChanges(view, owner, [{ key: "quality", lead: false }]).length, 1);
  assert.deepEqual(teamRequest(view, changes, "k"), { expected_revision: 4, request_key: "k", changes });
});

test("a deactivated role stays selectable only for a member who already holds it", () => {
  assert.deepEqual(selectableRoles(view, []).map(role => role.key), ["mechanical", "quality"]);
  assert.deepEqual(selectableRoles(view, view.members[2].roles).map(role => role.key), ["mechanical", "quality", "battery_safety"]);
});

test("a missing or expired grant reads as needing a category grant", () => {
  assert.deepEqual(["write", "read", "expired", "missing"].map(needsGrant), [false, false, true, true]);
  assert.deepEqual(["write", "read", "expired", "missing"].map(grantLabel), ["可办理", "只读授权", "需要品类授权", "需要品类授权"]);
  assert.equal(teamPath("a", "b"), "v1/products/a/projects/b/team");
});

test("unhanded work reads in words and is empty once handed over", () => {
  assert.equal(pendingText({ tasks: 1, commitments: 2, external_waits: 0 }), "任务 1、承诺 2");
  assert.equal(pendingText({ tasks: 0, commitments: 0, external_waits: 0 }), "");
  assert.equal(pendingText(null), "");
});
