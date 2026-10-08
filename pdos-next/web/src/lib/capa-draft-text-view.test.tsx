import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  capaDraftTextPayload, capaTextDraft, capaTextEditable, capaTextSnapshot,
} from "./capa-draft-text-view";
import { CapaDraftTextRevision } from "../components/builds/capa-draft-text-revision";
import {
  blankQualityLocal, qualityCommand, qualityPayloadReads, qualityReads,
  qualityTier, restoreQualityLocal, type QualityIssue,
} from "./build-quality-loop-view";

const source = { id: "original-source", revision: 2, kind: "artifact", position: `line:3;quote_sha256:${"a".repeat(64)}` };
function issue(): QualityIssue {
  return {
    id: "immutable-issue-v4", issue_id: "logical-issue", revision: 4, is_current: true, source_status: "current",
    capabilities: { "quality.capa.draft": true }, authority: {}, failures: [], followup_needs: [],
    required_source_read_set: [{ artifact_id: source.id, expected_revision: source.revision }],
    issue: {
      title: "固定原失败", status: "actioning", root_cause: null, closure: null,
      needs_recheck: false, merged_into: null, failures: [{ identity: "failure-b" }, { identity: "failure-a" }],
      capa: {
        id: "same-capa", hypotheses: [{ text: "有来源假设", sources: [source] }],
        actions: [
          { id: "first-action", kind: "corrective", text: "准备材料并执行复验", executor_id: "maker", completion: null },
          { id: "second-action", kind: "preventive", text: "保留独立原件", executor_id: "another-member", completion: null },
        ],
        requirement: {
          method: "固定后续方法", acceptance: "精确全部原失败通过",
          observation_until: "2026-10-04T02:20:00.123456+00:00", required_failure_ids: ["failure-a", "failure-b"],
        },
        effectiveness: null, effectiveness_history: [],
      },
    },
  };
}
function changed(row = issue()) {
  const draft = capaTextDraft(row)!;
  draft.actions[0].text = "准备并保留完整材料";
  return draft;
}

test("text successor clones exact fixed CAPA material, ordered identities and original time spelling", () => {
  const row = issue(), before = structuredClone(row), draft = changed(row), payload = capaDraftTextPayload(row, draft);
  const fixed = row.issue.capa as Record<string, unknown>;
  assert.deepEqual(payload, {
    issue_id: row.issue_id, expected_issue_revision: row.revision, capa_id: fixed.id,
    hypotheses: fixed.hypotheses, actions: [
      { ...(fixed.actions as Record<string, unknown>[])[0], text: draft.actions[0].text },
      (fixed.actions as Record<string, unknown>[])[1],
    ], requirement: fixed.requirement,
  });
  assert.deepEqual(row, before);
  (payload.hypotheses as { sources: typeof source[] }[])[0].sources[0].position = "client mutation";
  assert.deepEqual(row, before);
  assert.equal("confirmation_token" in payload, false);
  assert.equal("root_cause" in payload, false);
  assert.equal("qualified" in payload, false);
});

for (const drift of ["capa", "id", "kind", "executor", "hypothesis", "requirement", "source", "order", "new", "delete"]) {
  test(`fixed draft refuses ${drift} drift without creating any new identity`, () => {
    const row = issue(), draft = changed(row);
    if (drift === "order") draft.actions.reverse();
    else if (drift === "new") draft.actions.push({ id: "new-action", text: "新的措施" });
    else if (drift === "delete") draft.actions.pop();
    else if (drift === "capa") draft.fixedCapa.id = "new-capa";
    else if (drift === "hypothesis") draft.fixedCapa.hypotheses[0].text = "另一假设";
    else if (drift === "requirement") draft.fixedCapa.requirement.observation_until = "2026-10-05T00:00:00Z";
    else if (drift === "source") (draft.fixedCapa.hypotheses[0].sources as typeof source[])[0].revision++;
    else if (drift === "id") draft.fixedCapa.actions[0].id = "new-action";
    else if (drift === "kind") draft.fixedCapa.actions[0].kind = "preventive";
    else draft.fixedCapa.actions[0].executor_id = "new-person";
    assert.throws(() => capaDraftTextPayload(row, draft));
  });
}

for (const blocker of ["historical", "source", "capability", "root", "completion", "effectiveness", "effectiveness_history", "closure", "needs_recheck", "merged"]) {
  test(`server/factual ${blocker} keeps an existing CAPA readonly`, () => {
    const row = issue(), draft = changed(row), capa = row.issue.capa as Record<string, unknown>;
    if (blocker === "historical") row.is_current = false;
    else if (blocker === "source") row.source_status = "needs_recheck";
    else if (blocker === "capability") row.capabilities["quality.capa.draft"] = false; // Includes actual saved Link exclusion.
    else if (blocker === "completion") (capa.actions as Record<string, unknown>[])[0].completion = { id: "actual" };
    else if (blocker === "effectiveness") capa.effectiveness = { result: "ineffective" };
    else if (blocker === "effectiveness_history") capa.effectiveness_history = [{ result: "ineffective" }];
    else if (blocker === "root") row.issue.root_cause = { text: "具名结论" };
    else if (blocker === "closure") row.issue.closure = { text: "已关闭" };
    else if (blocker === "needs_recheck") row.issue.needs_recheck = true;
    else row.issue.merged_into = "target";
    assert.equal(capaTextEditable(row), false);
    assert.throws(() => capaDraftTextPayload(row, draft));
  });
}

test("draft cannot follow another immutable version or logical Issue after a late read", () => {
  const row = issue(), draft = changed(row);
  for (const next of [{ ...row, id: "next-immutable" }, { ...row, issue_id: "another-logical" }, { ...row, revision: 5 }]) {
    assert.throws(() => capaDraftTextPayload(next, draft));
  }
});

test("empty/overlong/unchanged action text does not produce a new command", () => {
  const row = issue();
  assert.throws(() => capaDraftTextPayload(row, capaTextDraft(row)!));
  for (const text of [" ", "x".repeat(2001)]) {
    const draft = changed(row); draft.actions[0].text = text;
    assert.throws(() => capaDraftTextPayload(row, draft));
  }
});

test("T0 and UNKNOWN reuse existing full Command/recovery shape with no new proof or key", () => {
  const row = issue(), payload = capaDraftTextPayload(row, changed(row));
  const command = qualityCommand({ id: "product", revision: 9 }, "quality.capa.draft", payload,
    qualityReads(row.required_source_read_set, qualityPayloadReads(payload)), "original-command", "original-key");
  assert.equal(qualityTier(command.operation), "T0");
  assert.equal("confirmation_token" in command.payload, false);
  for (const stage of ["inputs", "execute"] as const) {
    const local = { ...blankQualityLocal(), pending: { stage, command } };
    const restored = restoreQualityLocal({ schema_version: 1, product_id: "product", principal_id: "maker", ...local }, "product", "maker");
    assert.deepEqual(restored?.pending, local.pending);
    assert.equal(restored?.pending && "command" in restored.pending ? restored.pending.command.idempotency_key : null, "original-key");
  }
});

test("complete inherited sources plus fixed hypothesis stay exact and overflow is never cropped", () => {
  const row = issue(), payload = capaDraftTextPayload(row, changed(row));
  const inherited = Array.from({ length: 20 }, (_, i) => ({ artifact_id: `source-${i}`, expected_revision: 1 }));
  assert.throws(() => qualityReads(inherited, qualityPayloadReads(payload)), /20/);
  assert.deepEqual(qualityReads(row.required_source_read_set, qualityPayloadReads(payload)), row.required_source_read_set);
});

test("malformed or absent fixed actions have no editable successor form", () => {
  const row = issue(); row.issue.capa = null;
  assert.equal(capaTextSnapshot(row), null);
  const malformed = issue(), capa = malformed.issue.capa as Record<string, unknown>;
  (capa.actions as Record<string, unknown>[])[1].id = "first-action";
  assert.equal(capaTextDraft(malformed), null);
});

function rendered(row = issue(), disabled = false) {
  return renderToStaticMarkup(createElement(CapaDraftTextRevision, {
    issue: row, disabled, names: new Map([["maker", "实际原责任人"]]),
    onSave: () => { throw new Error("server render cannot submit a business command"); },
  }));
}

test("real React component exposes only original action text controls, no identity/date/add/remove controls", () => {
  const html = rendered();
  assert.equal((html.match(/<textarea/g) ?? []).length, 2);
  assert.equal((html.match(/<select|<input/g) ?? []).length, 0);
  assert.match(html, /准备材料并执行复验/);
  assert.match(html, /实际原责任人/);
  assert.match(html, /2026-10-04T02:20:00.123456\+00:00/);
  assert.match(html, /核对并保存文本续版/);
  assert.doesNotMatch(html, /增加|移除此|一次确认/);
  assert.match(html, /<button[^>]*disabled=""/); // Unchanged material never sends.
});

test("pending/common lock disables real component text entry and server capability denial also disables it", () => {
  assert.match(rendered(issue(), true), /<fieldset disabled=""/);
  const row = issue(); row.capabilities["quality.capa.draft"] = false;
  assert.match(rendered(row), /<fieldset disabled=""/);
  assert.match(rendered(row), /以服务器最新核对为准/);
});
