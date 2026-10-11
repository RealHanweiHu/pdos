import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  blankMpLocal, mpBlankPayload, mpCancelled, mpContinuation, mpDecimal, mpDocumentChoices, mpFailure, mpFixedMaterial, mpFixedVersion, mpInputs, mpNames, mpOperation, mpPayloadReads, mpPrepared, mpReading, mpReceipt, mpSaved, mpScopeChanged, mpSemantic, newMpCommand, restoreMpLocal, validMpBody, validMpParameter, validMpPayload, validMpSource,
  type MpApi, type MpBody, type MpKind, type MpPayload, type MpPending, type MpPrepared, type MpReview, type MpSource, type MpVersion,
} from "./manufacturing-preparation-contract";
import { runMpRequest } from "./manufacturing-preparation-actions";
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const project = id(1), process = { id: id(2), revision: 3, name: "固定装配", operations: [{ key: "assemble", name: "装配" }] }, product = { id: id(3), revision: 4 }, actor = id(4);
const source = (n = 5): MpSource => ({ artifact_id: id(n), expected_revision: 1, line: 1, quote: "完整原文，11.0000 V" });
const clone = <T>(v: T): T => structuredClone(v);
function payload(kind: MpKind = "work_instruction"): MpPayload { const p = mpBlankPayload(kind, project, process); p.title = "装配固定草稿"; p.reason = "具名记录拟定资料"; p.sources = [source()]; if ("steps" in p) { p.operation_key = "assemble"; p.steps[0].text = "依原图装配"; p.steps[0].sources = [source()]; } if ("checks" in p) { p.operation_key = "assemble"; p.checks[0].feature = "装配间隙"; p.checks[0].sources = [source()]; } return p; }
function body(p: MpPayload, kind: MpKind = "work_instruction"): MpBody { return { schema_version: "pdos-manufacturing-preparation-v1", kind, status: "draft", input: clone(p), scope: { project_id: project, purpose: "内部合成调查" }, process_snapshot: process, document_bindings: [], gaps: [{ code: "MANUFACTURING_BASELINE_RELEASE_NOT_CONFIGURED", detail: "制造基线尚无具名发布决定。" }], qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false }; }
function command(kind: MpKind = "work_instruction") { return newMpCommand(product, kind, payload(kind), id(10), id(11)); }
function review(commandValue = command()): MpReview { return { operation: commandValue.operation, before: null, after: { id: null, revision: 1, status: "draft", created_at: null, time_policy: "server_on_save", body: body(commandValue.payload, commandValue.operation === "npi.control_plan.record" ? "control_plan" : commandValue.operation === "npi.manufacturing_baseline.record" ? "manufacturing_baseline" : "work_instruction") }, effect: "只保存制造准备草稿，不发布或授试产。", authority: { scope: { tenant_id: id(12), product_id: product.id, project_id: project }, subject_id: actor, operation: commandValue.operation, purpose: "内部合成调查", authorized: true, qualified: true, roles: ["manufacturing"], synthetic: true, reason_codes: [], valid_until: "2100-01-01T00:00:00+00:00", required_source_read_set: commandValue.source_read_set }, required_source_read_set: commandValue.source_read_set, reason: commandValue.payload.reason, read_basis: { exact: "actual host material substitute" } }; }
function version(p = payload()): MpVersion { return { schema_version: "pdos-manufacturing-preparation-v1", id: id(14), kind: "work_instruction", revision: 1, series_id: id(14), project_id: project, owner_id: actor, visibility: "private", title: p.title, status: "draft", purpose: "内部合成调查", process: p.process, operation_key: "assemble", previous_id: null, previous_revision: null, created_at: "2026-10-03T12:34:56.123456+00:00", is_current: true, source_status: "current", required_source_read_set: [{artifact_id:source().artifact_id,expected_revision:source().expected_revision}], body: body(p), sources: [source()], receipt_id: id(15), manufacturing_release: null, qualification: "unknown", negative_enumeration_complete: false }; }
function prepared(c = command()): MpPrepared { return { command: { ...clone(c), payload: { ...clone(c.payload), confirmation_token: "server-returned-token-substitute" } }, expires_at: "2100-01-01T00:00:00+00:00", review: review(c) }; }
for (const kind of Object.keys(mpNames) as MpKind[]) test(`actual ${kind} payload retains unknown and draft-only meaning`, () => { const p = payload(kind); assert.equal(validMpPayload(p, kind), true); assert.equal(validMpBody(body(p, kind), kind), true); assert.equal(p.visibility, "private"); assert.equal(mpBlankPayload(kind, project, process).reason, ""); });
test("typed blanks do not insert zero, invented facts, source or received time", () => { const p = mpBlankPayload("control_plan", project, process); assert.ok("checks" in p); assert.equal(p.checks[0].criterion, null); assert.deepEqual(p.sources, []); for(const extra of ["qualified", "released", "received_at", "issuer", "approval_token"]) assert.equal(validMpPayload({ ...payload(), [extra]: true }, "work_instruction"), false); });
for (const quote of ["one\ntwo", "one\rtwo", "\0", "\ud800", "x".repeat(4001)]) test("exact source rejects cross-line/NUL/surrogate/overbound " + quote.length, () => { assert.equal(validMpSource({ ...source(), quote }), false); });
test("source choices retain complete quote and reject duplicate refs", () => { const p = payload(); p.sources = [source(), source()]; assert.equal(validMpPayload(p,"work_instruction"), false); assert.equal(validMpSource(source()), true); });
for (const number of [true, 0.1, "NaN", "Infinity", "1e", "0.0000000000001", "100000000000000000000"]) test("finite exact decimal bound rejects " + String(number), () => assert.equal(mpDecimal(number), null));
test("declared decimal normalization only compares numeric meaning and cannot rewrite original source", () => { const c = command(); assert.ok("steps" in c.payload); c.payload.steps[0].parameters = [{ key:"gap", nominal:"01.2000", lower:null, upper:null, unit:"mm", sources:[source()] }]; const result = prepared(c); assert.ok("steps" in result.command.payload); result.command.payload.steps[0].parameters[0].nominal = "1.2000"; result.review.after.body.input = clone(result.command.payload); delete result.review.after.body.input.confirmation_token; assert.ok(mpPrepared(result,c,actor)); assert.equal(c.payload.steps[0].parameters[0].nominal,"01.2000"); assert.equal(c.payload.steps[0].parameters[0].sources[0].quote,source().quote); result.command.payload.steps[0].parameters[0].nominal="1.200000000001"; assert.equal(mpPrepared(result,c,actor),null); });
test("known parameter requires unit+independent source and exact lower-upper order", () => { const p = { key:"pressure", nominal:null, lower:"-1.000000000001", upper:"-1.000000000002", unit:"bar", sources:[source()] }; assert.equal(validMpParameter(p),false); assert.equal(validMpParameter({...p,lower:"-2"}),true); assert.equal(validMpParameter({...p,lower:"-2",unit:null}),false); assert.equal(validMpParameter({...p,lower:null,upper:null,unit:null,sources:[]}),true); });
test("source closure keeps multiple lines but refuses conflicting revision instead of overwrite", () => { const p = payload(); p.sources = [source(), { ...source(), line:2, quote:"另一整行" }]; assert.equal(mpPayloadReads(p).length,1); assert.ok("steps" in p); p.steps[0].sources = [{...source(),expected_revision:2}]; assert.throws(()=>mpPayloadReads(p),/冲突版本/); });
test("source closure keeps all 21 distinct exact sources", () => { const p=payload(); p.sources=Array.from({length:20},(_,i)=>source(i+30)); assert.ok("steps" in p); p.steps[0].sources=[source(60)]; assert.deepEqual(new Set(mpPayloadReads(p).map(row=>row.artifact_id)),new Set([...p.sources,source(60)].map(row=>row.artifact_id))); });
test("inputs only allow server-supplied full reads change, never command/key/scope/payload", () => { const c=command(), server={...clone(c),source_read_set:[...c.source_read_set,{artifact_id:id(50),expected_revision:1}]}, r=review(server); assert.ok(mpInputs({command:server,review:r},c,actor)); for(const changed of [{...server,idempotency_key:id(51)},{...server,payload:{...server.payload,reason:"换内容"}},{...server,payload:{...server.payload,confirmation_token:"not-an-input-proof"}}]) assert.equal(mpInputs({command:changed,review:r},c,actor),null); });
test("inputs complete readset must retain explicit exact selected source", () => { const c=command(), server={...clone(c),source_read_set:[]}; assert.equal(mpInputs({command:server,review:review(server)},c,actor),null); });
test("preview keeps original prepared command and requires one actual server T1 token", () => { const c=command(), p=prepared(c), actual=mpPrepared(p,c,actor); assert.ok(actual); assert.equal(actual.command,p.command); const missing=clone(p); delete missing.command.payload.confirmation_token; assert.equal(mpPrepared(missing,c,actor),null); assert.equal(mpPrepared({...p,expires_at:"2000-01-01T00:00:00Z"},c,actor),null); });
test("preview rejects caller/product/project/role or qualification substitutions", () => { const c=command(); for(const update of [{subject_id:id(70)},{qualified:null},{authorized:false},{roles:["engineering"]},{scope:{tenant_id:id(12),product_id:id(71),project_id:project}}]) { const p=prepared(c); Object.assign(p.review.authority,update); assert.equal(mpPrepared(p,c,actor),null); } });
test("preview rejects source quote and raw text drift even if all IDs match", () => { const c=command(); const p=prepared(c); p.command.payload.sources[0].quote+="changed"; assert.equal(mpPrepared(p,c,actor),null); const other=prepared(c); assert.ok("steps" in other.review.after.body.input); other.review.after.body.input.steps[0].text="另一作业"; assert.equal(mpPrepared(other,c,actor),null); });
test("prepared stable unknown body cannot claim released/Pilot/known/full-enumeration", () => { for(const patch of [{status:"released"},{qualification:"known"},{manufacturing_release:{}},{negative_enumeration_complete:true}]) { const b=body(payload()); Object.assign(b,patch); assert.equal(validMpBody(b,"work_instruction"),false); } });
test("scoped history retains source-stale and old version read only without hidden ACL guessing", () => { const saved=version(); saved.source_status="needs_recheck"; saved.is_current=false; const reading={schema_version:"pdos-manufacturing-preparation-v1",versions:[saved],has_more:false,unavailable_count:1,qualification:"unknown",manufacturing_release:null,negative_enumeration_complete:false}; assert.ok(mpReading(reading,project,process.id)); assert.equal(mpReading(reading,id(72),process.id),null); assert.equal(mpReading(reading,project,id(73)),null); });
test("actual continuation binds exact current pre-version in substantive before/after", () => { const old=version(), p=payload(); p.previous_id=old.id; p.expected_previous_revision=1; const c=newMpCommand(product,"work_instruction",p,id(10),id(11)), r=prepared(c); r.review.before=old; r.review.after.revision=2; assert.ok(mpPrepared(r,c,actor)); r.review.before.id=id(74); assert.equal(mpPrepared(r,c,actor),null); });
test("UNKNOWN original command/key/payload cannot migrate to other scope or kind", () => { const state=blankMpLocal(product.id,actor), c=command(); Object.assign(state,{project_id:project,process_id:process.id,draft:c.payload,pending:{stage:"execute",command:prepared(c).command}}); const same=mpScopeChanged(state,id(80),id(81),"control_plan"); assert.equal(same,state); assert.ok(restoreMpLocal(same,product.id,actor)); assert.equal(restoreMpLocal(same,product.id,id(82)),null); const switched=clone(state); switched.process_id=id(83); assert.equal(restoreMpLocal(switched,product.id,actor),null); });
test("unsent scope selection clears draft rather than silently rebinding payload", () => { const local=blankMpLocal(product.id,actor); local.draft=payload(); local.project_id=project; local.process_id=process.id; const next=mpScopeChanged(local,project,id(84),"control_plan"); assert.equal(next.draft,null); assert.equal(next.process_id,id(84)); });
test("saved receipt precedes later read failure, clears pending and cannot become unknown", () => { const c=command(), local=blankMpLocal(product.id,actor); local.pending={stage:"execute",command:prepared(c).command}; const receipt={operation:"npi.work_instruction.record" as const,id:id(85),subject_id:id(86),subject_type:"work_instruction" as const,subject_revision:1}; const saved=mpSaved(local,receipt); assert.equal(saved.pending,null); assert.deepEqual(mpFailure(saved,500),{clearPrivate:false,saved:true,unknown:false}); assert.deepEqual(mpFailure(saved,403),{clearPrivate:true,saved:true,unknown:false}); assert.equal(mpFailure(local,500).unknown,true); });
test("receipt family exact, ordinary read cancel distinct from network and forbidden",()=>{ const receipt={operation:"npi.control_plan.record" as const,id:id(85),subject_id:id(86),subject_type:"control_plan",subject_revision:1}; assert.equal(mpReceipt(receipt,mpOperation("work_instruction")),false); assert.equal(mpReceipt({...receipt,subject_type:undefined},undefined as never),false); assert.equal(mpCancelled({code:"READ_SUPERSEDED"}),true); assert.equal(mpCancelled({status:500}),false); });
test("semantic excludes only confirmation, preserves all original choices/source order",()=>{ const p=payload(); p.confirmation_token="whole-server-token-substitute"; const semantic=mpSemantic(p); assert.equal("confirmation_token" in semantic,false); assert.deepEqual(semantic.sources,p.sources); assert.equal((semantic.sources as MpSource[])[0].quote,source().quote); });

test("Pydantic scientific Decimal preview is equal only for declared numerical material", () => {
  const c=command(); assert.ok("steps" in c.payload); c.payload.steps[0].parameters=[{key:"gap",nominal:"0.000000000001",lower:null,upper:null,unit:"mm",sources:[source()]}];
  const p=prepared(c); assert.ok("steps" in p.command.payload); p.command.payload.steps[0].parameters[0].nominal="1E-12"; p.review.after.body.input=clone(p.command.payload); delete p.review.after.body.input.confirmation_token;
  assert.ok(mpPrepared(p,c,actor)); assert.equal(c.payload.steps[0].parameters[0].nominal,"0.000000000001");
  p.command.payload.steps[0].parameters[0].nominal="2E-12"; assert.equal(mpPrepared(p,c,actor),null);
});
test("fixed operation and baseline document set reject omitted, substituted and duplicate material", () => {
  const wi=body(payload()); assert.ok("operation_key" in wi.input); wi.input.operation_key="invented"; assert.equal(validMpBody(wi,"work_instruction"),false);
  const baseline=body(payload("manufacturing_baseline"),"manufacturing_baseline"); assert.ok("operations" in baseline.input);
  baseline.input.operations[0].work_instruction={kind:"work_instruction",id:id(99),revision:2};
  assert.equal(validMpBody(baseline,"manufacturing_baseline"),false);
  baseline.document_bindings=[{operation_key:"assemble",kind:"work_instruction",id:id(99),revision:2,body_sha256:"a".repeat(64)}];
  assert.equal(validMpBody(baseline,"manufacturing_baseline"),true);
  baseline.document_bindings.push(clone(baseline.document_bindings[0])); assert.equal(validMpBody(baseline,"manufacturing_baseline"),false);
});

test("incomplete current-scope local form survives reload without becoming a valid write",()=>{
  const local=blankMpLocal(product.id,actor); local.project_id=project; local.process_id=process.id; local.draft=mpBlankPayload("work_instruction",project,process);
  assert.ok("steps" in local.draft); local.draft.steps[0].parameters=[{key:"",nominal:"-",lower:null,upper:null,unit:null,sources:[]}];
  assert.ok(restoreMpLocal(local,product.id,actor)); assert.equal(validMpPayload(local.draft,"work_instruction"),false);
  assert.throws(()=>newMpCommand(product,"work_instruction",local.draft!,id(10),id(11)));
  local.process_id=id(66); assert.equal(restoreMpLocal(local,product.id,actor),null);
});

test("history cannot swap visibility/purpose/precise inputs behind a valid fixed body",()=>{
  for(const patch of [{visibility:"category"},{purpose:"另一用途"},{sources:[]},{operation_key:"other"}]) {
    const row=version(); Object.assign(row,patch); const reading={schema_version:"pdos-manufacturing-preparation-v1",versions:[row],has_more:false,unavailable_count:0,qualification:"unknown",manufacturing_release:null,negative_enumeration_complete:false};
    assert.equal(mpReading(reading,project,process.id),null);
  }
});
test("review authority source closure and continuation owner must remain exact",()=>{
  const c=command(), p=prepared(c); p.review.authority.required_source_read_set=[{artifact_id:id(98),expected_revision:1}]; assert.equal(mpPrepared(p,c,actor),null);
  const old=version(), next=payload(); next.previous_id=old.id; next.expected_previous_revision=1;
  const continued=newMpCommand(product,"work_instruction",next,id(10),id(11)), r=prepared(continued); r.review.before=old; r.review.after.revision=2; r.review.before.owner_id=id(97); assert.equal(mpPrepared(r,continued,actor),null);
});

test("confirmation and actual authority deadlines independently expire, without rewriting the prepared request", () => {
  const c = command(), p = prepared(c), now = Date.parse("2026-10-05T12:00:00Z");
  p.review.authority.valid_until = "2026-10-05T12:00:00Z";
  const original = clone(p);
  assert.equal(mpPrepared(p, c, actor, now), null);
  assert.deepEqual(p, original);
  p.review.authority.valid_until = "2026-10-05T12:00:01Z";
  assert.ok(mpPrepared(p, c, actor, now));
  p.expires_at = "2026-10-05T12:00:00Z";
  assert.equal(mpPrepared(p, c, actor, now), null);
  p.expires_at = "2100-01-01T00:00:00";
  assert.equal(mpPrepared(p, c, actor, now), null);
});

test("local pending restoration rejects token on read stages, mismatched material, and contradictory saved outcome", () => {
  const c = command(), state = blankMpLocal(product.id, actor);
  Object.assign(state, { project_id: project, process_id: process.id, draft: clone(c.payload), pending: { stage: "execute", command: prepared(c).command } });
  assert.ok(restoreMpLocal(state, product.id, actor));
  for (const stage of ["inputs", "preview"] as const) {
    const invalid = clone(state); invalid.pending!.stage = stage;
    assert.equal(restoreMpLocal(invalid, product.id, actor), null);
  }
  const changed = clone(state); changed.draft!.reason = "本机原材料被改写";
  assert.equal(restoreMpLocal(changed, product.id, actor), null);
  const contradictory = clone(state); contradictory.savedReceipt = { operation: c.operation, id: id(85), subject_id: id(86), subject_type: "work_instruction", subject_revision: 1 };
  assert.equal(restoreMpLocal(contradictory, product.id, actor), null);
});

test("baseline keeps every fixed Process operation and rejects stale, wrong-scope or widened child choices", () => {
  const p = payload("manufacturing_baseline"), current = version();
  assert.ok("operations" in p);
  p.operations[0].work_instruction = { kind: current.kind, id: current.id, revision: current.revision };
  assert.equal(mpFixedMaterial(p, process, [current]), true);
  const original = clone(p);
  for (const patch of [{ is_current: false }, { source_status: "needs_recheck" }, { project_id: id(90) }, { operation_key: "other" }, { process: { id: process.id, revision: 4 } }]) {
    assert.equal(mpDocumentChoices([{ ...current, ...patch } as MpVersion], p, "assemble", "work_instruction").length, 0);
    assert.equal(mpFixedMaterial(p, process, [{ ...current, ...patch } as MpVersion]), false);
  }
  assert.equal(mpFixedMaterial(p, { ...process, operations: [...process.operations, { key: "inspect", name: "检验" }] }, [current]), false);
  p.visibility = "category";
  assert.equal(mpFixedMaterial(p, process, [current]), false);
  p.visibility = "private"; p.operations[0].work_instruction = null;
  assert.equal(mpFixedMaterial(p, process, []), true); // An explicit missing document remains a server-reported gap.
  assert.equal(original.operations[0].work_instruction!.id, current.id);
});

test("fixed historical child may be stale and noncurrent but cannot swap its identity, scope or operation", () => {
  const row = version(), ref = { kind: row.kind, id: row.id, revision: row.revision };
  row.is_current = false; row.source_status = "needs_recheck";
  assert.ok(mpFixedVersion(row, ref, project, process, "assemble"));
  assert.equal(mpFixedVersion(row, { ...ref, revision: 2 }, project, process, "assemble"), null);
  assert.equal(mpFixedVersion(row, ref, id(99), process, "assemble"), null);
  assert.equal(mpFixedVersion(row, ref, project, { ...process, revision: 4 }, "assemble"), null);
  assert.equal(mpFixedVersion(row, ref, project, process, "other"), null);
});

test("continuation copies only the exact own Current and retains fixed material and history", () => {
  const row = version(), original = clone(row), p = mpContinuation(row, actor, project, process);
  assert.ok(p);
  assert.equal(p.previous_id, row.id); assert.equal(p.expected_previous_revision, row.revision);
  assert.equal(p.reason, ""); assert.deepEqual(p.process, row.process);
  assert.deepEqual(p.sources, row.sources); assert.equal(p.visibility, row.visibility);
  assert.deepEqual(row, original);
  assert.equal(mpContinuation(row, id(99), project, process), null);
  assert.equal(mpContinuation({ ...row, is_current: false }, actor, project, process), null);
  assert.equal(mpContinuation(row, actor, project, { ...process, revision: 4 }), null);
});

test("actual port pipeline stops at a complete T1 preview until explicit execute", async () => {
  const c = command(), requests: { path: string; body: unknown }[] = [], transitions: MpPending[] = [];
  const api: MpApi = async <T>(path: string, request?: unknown) => {
    requests.push({ path, body: clone(request) });
    if (path.endsWith("/inputs")) return { command: c, review: review(c) } as T;
    if (path === "v1/commands/preview") return prepared(c) as T;
    throw new Error("A write must require explicit confirmation.");
  };
  const result = await runMpRequest(api, product.id, actor, { stage: "inputs", command: c }, next => transitions.push(next), () => true);
  assert.equal(result?.stage, "preview");
  assert.deepEqual(requests.map(r => r.path), [`v1/products/${product.id}/manufacturing-preparations/inputs`, "v1/commands/preview"]);
  assert.equal(transitions.length, 1); assert.equal(transitions[0].stage, "preview");
  assert.deepEqual(requests[0].body, requests[1].body);
});

test("lost response and original recovery use the same confirmed command, token and key with no new preview", async () => {
  const confirmed = prepared().command, waiting: MpPending = { stage: "execute", command: confirmed }, sent: unknown[] = [];
  const receipt = { operation: confirmed.operation, id: id(85), subject_id: id(86), subject_type: "work_instruction", subject_revision: 1 };
  const api: MpApi = async <T>(path: string, request?: unknown) => {
    assert.equal(path, "v1/commands"); sent.push(clone(request));
    if (sent.length === 1) throw new Error("transport response lost after commit");
    return receipt as T;
  };
  await assert.rejects(runMpRequest(api, product.id, actor, waiting, () => assert.fail("no read-stage transition"), () => true), /response lost/);
  assert.deepEqual(await runMpRequest(api, product.id, actor, waiting, () => assert.fail("no new preview"), () => true), { stage: "saved", receipt });
  assert.equal(sent.length, 2); assert.deepEqual(sent[0], confirmed); assert.deepEqual(sent[0], sent[1]);
  assert.equal(waiting.command, confirmed);
});

test("UNKNOWN server qualification refusal preserves the original request without renewal or resubmission", async () => {
  const waiting: MpPending = { stage: "execute", command: prepared().command }, original = clone(waiting), requests: string[] = [];
  const api: MpApi = async () => { requests.push("execute"); throw { status: 403, code: "MISSING_QUALIFICATION" }; };
  await assert.rejects(runMpRequest(api, product.id, actor, waiting, () => assert.fail("no new inputs"), () => true), { status: 403, code: "MISSING_QUALIFICATION" });
  assert.deepEqual(waiting, original); assert.deepEqual(requests, ["execute"]);
});

test("disposed read scope cannot continue to preview or write", async () => {
  const c = command(), requests: string[] = []; let active = true;
  const api: MpApi = async <T>(path: string) => { requests.push(path); active = false; return { command: c, review: review(c) } as T; };
  assert.equal(await runMpRequest(api, product.id, actor, { stage: "inputs", command: c }, () => assert.fail("disposed context"), () => active), null);
  assert.equal(requests.length, 1);
});

test("wrong continuation receipt cannot be accepted as a saved outcome", async () => {
  const p = payload(); p.previous_id = id(14); p.expected_previous_revision = 1;
  const c = newMpCommand(product, "work_instruction", p, id(10), id(11)); c.payload.confirmation_token = "server-returned-token-substitute";
  const api: MpApi = async <T>() => ({ operation: c.operation, id: id(85), subject_id: id(86), subject_type: "work_instruction", subject_revision: 1 }) as T;
  await assert.rejects(runMpRequest(api, product.id, actor, { stage: "execute", command: c }, () => {}, () => true), /固定续版/);
});

test("ordinary authority has no aggregate deadline while T1 expiry remains required", () => {
  const c = command(), p = prepared(c), at = Date.parse("2026-10-08T12:00:00Z");
  p.review.authority.valid_until = null;
  assert.ok(mpPrepared(p, c, actor, at));
  p.expires_at = "2026-10-08T12:00:00Z";
  assert.equal(mpPrepared(p, c, actor, at), null);
});
