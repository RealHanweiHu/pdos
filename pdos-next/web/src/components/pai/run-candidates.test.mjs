import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
let hooks;
const equal = (a,b) => a && b && a.length === b.length && a.every((value,index) => Object.is(value,b[index]));
const reactShim = { ...React,
 useState(initial) { const own=hooks,index=own.index++; if (!(index in own.values)) own.values[index]=typeof initial === "function"?initial():initial; return [own.values[index],value=>{own.values[index]=typeof value === "function"?value(own.values[index]):value;}]; },
 useRef(initial) { const index=hooks.index++; return hooks.values[index] ??= {current:initial}; },
 useCallback(callback,deps) { const index=hooks.index++,old=hooks.values[index]; if (!old || !equal(old.deps,deps)) hooks.values[index]={deps,value:callback}; return hooks.values[index].value; },
 useEffect(effect,deps) { const own=hooks,index=own.index++,old=own.values[index]; if (!old || !equal(old.deps,deps)) { own.effects.push(()=>{old?.cleanup?.(); own.values[index]={deps,cleanup:effect()};}); } },
};
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? reactShim
    : specifier === "@phosphor-icons/react" ? { Sparkle: () => React.createElement("svg") }
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}
const { RunCandidates } = load(path.join(directory,"run-candidates.tsx"));
const category="11111111-1111-4111-8111-111111111111", run="22222222-2222-4222-8222-222222222222", event="33333333-3333-4333-8333-333333333333", snapshot="44444444-4444-4444-8444-444444444444";
const original = {command_id:run,idempotency_key:"actual-original-key",category_id:category,product_id:null,operation:"research.snapshot.register",expected_revision:1,source_read_set:[],payload:{snapshot_id:snapshot,prepared_event_id:event}};
const receipt = {id:"receipt",operation:original.operation,subject_id:snapshot,subject_type:"public_web_snapshot",result:{}};
const pendingItem = {event_id:event,state:"pending",command_id:run,idempotency_key:original.idempotency_key,operation:original.operation,command:original,receipt:null,summary:{title:"Actual retained source",url:"https://maker.example/specs",visibility:"private",retrieved_at:"2026-10-16T00:00:00Z"}};
const storage = new Map();
globalThis.localStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function nodes(tree,predicate) { if (!tree || typeof tree!=="object") return []; if(Array.isArray(tree)) return tree.flatMap(value=>nodes(value,predicate)); return [...(predicate(tree)?[tree]:[]),...nodes(tree.props?.children,predicate)]; }
function text(tree) { if(typeof tree==="string" || typeof tree==="number") return String(tree); if(Array.isArray(tree)) return tree.map(text).join(""); return tree && typeof tree==="object" ? text(tree.props?.children):""; }
function session(api) {
 const state={values:[],index:0,effects:[]};let tree;
 const render=()=>{hooks=state;state.index=0;state.effects=[];try{const wrapper=RunCandidates({api,categoryId:category,principalId:"owner",runId:run,eventSequence:1});tree=wrapper.type(wrapper.props);return tree;}finally{hooks=null;}};
 return {render, async settle(){for(let i=0;i<6;i++){await tick();render();const effects=state.effects;state.effects=[];effects.forEach(effect=>effect());}return tree;},async click(label){render();const button=nodes(tree,node=>node.props?.onClick && text(node.props.children)===label)[0];assert.ok(button,label);assert.ok(!button.props.disabled,label);button.props.onClick({currentTarget:{focus(){}},preventDefault(){}});return this.settle();},unmount(){state.values.forEach(value=>value?.cleanup?.());},text:()=>text(render())};
}
function port(mode) {
 let committed=false,previews=0;const writes=[];
 return {writes,get previews(){return previews;},api:async(path,body)=>{
  if(path.includes("/candidates"))return {run_id:run,items:[committed?{...pendingItem,state:"adopted",command:null,receipt}:pendingItem],next_cursor:null};
  if(path.endsWith("/preview")){previews++;return {command:{...body,payload:{...body.payload,confirmation_token:"actual-preview-token"}},expires_at:"2099-01-01T00:00:00Z",review:{title:pendingItem.summary.title,url:pendingItem.summary.url,visibility:"private",effect:"登记实际读取来源"}};}
  writes.push(structuredClone(body));
  if(mode==="after_commit" && writes.length===1){committed=true;throw Error("Failed to fetch");}
  if(mode==="before_commit" && writes.length===1)throw Error("Failed to fetch");
  committed=true;return receipt;
 }};
}

test("snapshot is listed without a write, then one preview and one confirmation save it",async()=>{
 storage.clear();const p=port("success"),c=session(p.api);
 try{await c.settle();assert.equal(p.writes.length,0);assert.match(c.text(),/Actual retained source/);assert.match(c.text(),/原私有上下文受众/);
 await c.click("核对并预览研究来源登记");assert.equal(p.previews,1);
 await c.click("确认保存");assert.equal(p.writes.length,1);assert.match(c.text(),/研究来源登记已保存/);assert.equal(storage.size,0);
 }finally{c.unmount();}
});
test("lost success response restores the actual receipt on reopening without a second POST",async()=>{
 storage.clear();const p=port("after_commit"),first=session(p.api);let second;
 try{await first.settle();await first.click("核对并预览研究来源登记");await first.click("确认保存");assert.equal(storage.size,1);assert.ok(!first.text().includes("尚未保存"));first.unmount();
 second=session(p.api);await second.settle();assert.match(second.text(),/研究来源登记已保存/);assert.equal(p.writes.length,1);assert.equal(storage.size,0);
 }finally{first.unmount();second?.unmount();}
});
test("an uncommitted request remains recoverable with exactly its original command and token",async()=>{
 storage.clear();const p=port("before_commit"),first=session(p.api);let second;
 try{await first.settle();await first.click("核对并预览研究来源登记");await first.click("确认保存");first.unmount();second=session(p.api);await second.settle();
 await second.click("核对原请求");assert.equal(p.writes.length,2);assert.deepEqual(p.writes[1],p.writes[0]);assert.equal(p.previews,1);assert.equal(storage.size,0);
 }finally{first.unmount();second?.unmount();}
});


function pagedRecovery(state = "adopted", operation = original.operation) {
 const reads = [], writes = [], previews = [];
 const material = operation === original.operation ? original : { ...original, operation, payload: { prepared_by_run_id: run, candidate_digest: "a".repeat(64), title: "Retained synthetic proposal" } };
 const savedReceipt = { ...receipt, operation, subject_type: operation === "proposal.create" ? "proposal" : "public_web_snapshot" };
 const currentItem = { ...pendingItem, operation, command: material };
 const command = { ...material, payload: { ...material.payload, confirmation_token: "actual-original-token" } };
 storage.set(`pdos-next:run-candidate:owner:${category}:${run}`, JSON.stringify({ eventId: event, command }));
 const firstPage = Array.from({ length: 50 }, (_, index) => ({
  ...pendingItem, event_id: `older-event-${index}`, sequence: index + 1,
  state: "unavailable", command: null, receipt: null,
 }));
 firstPage[0] = { ...pendingItem, sequence: 1, event_id: "55555555-5555-4555-8555-555555555555", command: { ...original, payload: { ...original.payload, prepared_event_id: "55555555-5555-4555-8555-555555555555" } } };
 const api = async (url, body) => {
  if (url.includes("/candidates")) {
   reads.push(url);
   const after = Number(new URL(url, "https://local.test").searchParams.get("after"));
   return { run_id: run, items: after === 0 ? firstPage : [{
    ...currentItem, sequence: 51, state, command: state === "pending" ? material : null,
    receipt: state === "adopted" ? savedReceipt : null,
   }], next_cursor: after === 0 ? 50 : null };
  }
  if (url.endsWith("/preview")) { previews.push(body); throw Error("No new preview during recovery"); }
  writes.push(structuredClone(body)); return savedReceipt;
 };
 return { api, reads, writes, previews, command };
}

test("unknown saved response after the first 50 candidates can read on and restore its receipt without POST", async () => {
 storage.clear(); const p = pagedRecovery(), c = session(p.api);
 try {
  await c.settle(); assert.equal(p.reads.length, 1); assert.equal(storage.size, 1);
  const newPreviews = nodes(c.render(), node => node.props?.onClick && text(node.props.children) === "核对并预览研究来源登记");
  assert.ok(newPreviews.length > 0); assert.ok(newPreviews.every(node => node.props.disabled));
  await c.click("查看更多候选");
  assert.equal(p.reads.length, 2); assert.match(p.reads[1], /after=50/);
  assert.match(c.text(), /研究来源登记已保存/); assert.equal(storage.size, 0);
  assert.equal(p.previews.length, 0); assert.equal(p.writes.length, 0);
 } finally { c.unmount(); }
});

test("pending candidate on a later page keeps the original request and requires an explicit replay", async () => {
 storage.clear(); const p = pagedRecovery("pending"), c = session(p.api);
 try {
  await c.settle(); const saved = [...storage.values()][0];
  await c.click("查看更多候选");
  assert.equal(p.writes.length, 0); assert.equal([...storage.values()][0], saved);
  assert.ok(nodes(c.render(), node => node.props?.onClick && text(node.props.children) === "核对并预览研究来源登记").every(node => node.props.disabled));
  await c.click("核对原请求"); assert.deepEqual(p.writes, [p.command]);
  assert.equal(p.previews.length, 0); assert.equal(storage.size, 0);
 } finally { c.unmount(); }
});


test("proposal adoption on a later page restores the proposal link from its actual receipt", async () => {
 storage.clear(); const p = pagedRecovery("adopted", "proposal.create"), c = session(p.api);
 try {
  await c.settle(); await c.click("查看更多候选");
  assert.match(c.text(), /立项提案已保存/);
  assert.ok(nodes(c.render(), node => node.props?.href === `/categories/${category}/proposals/${snapshot}`).length > 0);
  assert.equal(storage.size, 0); assert.equal(p.writes.length, 0); assert.equal(p.previews.length, 0);
 } finally { c.unmount(); }
});

test("failed later-page read retains the exact request and refresh can recover the saved receipt", async () => {
 storage.clear(); const p = pagedRecovery(); let fail = true;
 const c = session(async (url, body) => {
  if (url.includes("after=50") && fail) { fail = false; throw Error("Synthetic page unavailable"); }
  return p.api(url, body);
 });
 try {
  await c.settle(); const saved = [...storage.values()][0]; await c.click("查看更多候选");
  assert.match(c.text(), /Synthetic page unavailable/); assert.equal([...storage.values()][0], saved);
  await c.click("刷新候选"); await c.click("查看更多候选");
  assert.match(c.text(), /研究来源登记已保存/); assert.equal(storage.size, 0);
  assert.equal(p.writes.length, 0); assert.equal(p.previews.length, 0);
 } finally { c.unmount(); }
});

for (const state of ["cancelled", "unavailable"]) test(`later-page ${state} candidate keeps unknown intent and blocks replay or a new preview`, async () => {
 storage.clear(); const p = pagedRecovery(state), c = session(p.api);
 try {
  await c.settle(); const saved = [...storage.values()][0]; await c.click("查看更多候选");
  const replay = nodes(c.render(), node => node.props?.onClick && text(node.props.children) === "核对原请求")[0];
  assert.ok(replay.props.disabled); assert.equal([...storage.values()][0], saved);
  const previews = nodes(c.render(), node => node.props?.onClick && text(node.props.children) === "核对并预览研究来源登记");
  assert.ok(previews.length > 0); assert.ok(previews.every(node => node.props.disabled));
  assert.equal(p.writes.length, 0); assert.equal(p.previews.length, 0);
 } finally { c.unmount(); }
});

test("later-page authority loss removes local recovery and does not send the original command", async () => {
 storage.clear(); const p = pagedRecovery();
 const c = session(async (url, body) => {
  if (url.includes("after=50")) throw Object.assign(Error("Synthetic current authority revoked"), { status: 403 });
  return p.api(url, body);
 });
 try {
  await c.settle(); await c.click("查看更多候选");
  assert.equal(storage.size, 0); assert.ok(!c.text().includes("保存结果待核对，已保留原请求"));
  assert.equal(p.writes.length, 0); assert.equal(p.previews.length, 0);
 } finally { c.unmount(); }
});
