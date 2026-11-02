import assert from "node:assert/strict";
import test from "node:test";
import { toggleContinuedSkill, validContinuedSkillExclusions, validSkillSelections } from "./continued-skills";

const recent = [
  { key: "public_research", version: "original-version", digest: "1".repeat(64) },
  { key: "gap_check", version: "second-original", digest: "2".repeat(64) },
];

test("continued choices preserve historical version identities and only accept exact fields", () => {
  assert.equal(validSkillSelections(recent, 2), true);
  for (const value of [null, [...recent, { ...recent[0], key: "third" }], [recent[0], recent[0]],
    [{ ...recent[0], digest: "invalid" }], [{ ...recent[0], version: "" }],
    [{ ...recent[0], enabled: true }], [{ ...recent[0], key: "k".repeat(161) }]]) {
    assert.equal(validSkillSelections(value, 2), false);
  }
});

test("removing and restoring a recent skill changes only exclusions and never its fixed identity", () => {
  const before = structuredClone(recent);
  assert.deepEqual(toggleContinuedSkill(recent, [], "public_research"), ["public_research"]);
  assert.deepEqual(toggleContinuedSkill(recent, ["public_research"], "public_research"), []);
  assert.deepEqual(toggleContinuedSkill(recent, ["gap_check"], "public_research"), ["public_research", "gap_check"]);
  assert.deepEqual(toggleContinuedSkill(recent, [], "unloaded"), []);
  assert.deepEqual(recent, before);
});

test("exclusions reject overlong, duplicate and non-key fields in original-request recovery", () => {
  assert.equal(validContinuedSkillExclusions([]), true);
  assert.equal(validContinuedSkillExclusions(["public_research", "gap_check"]), true);
  for (const value of [null, ["public_research", "public_research"], [""], [null],
    ["k".repeat(161)], ["first", "second", "third"], [{ key: "gap_check" }]]) {
    assert.equal(validContinuedSkillExclusions(value), false);
  }
});
