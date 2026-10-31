import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Actual component events/hooks and actual transport library. This is neither
// a browser nor PostgreSQL/qualification evidence; storage and HTTP are substitutes.
const directory = path.dirname(fileURLToPath(import.meta.url)), root = path.resolve(directory, "../../.."), dependency = createRequire(path.join(root, "package.json"));
const ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
const react = { ...React, useState(initial) { if (!hooks) return React.useState(initial); const own = hooks, index = own.index++; if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial; return [own.slots[index], value => { if (!own.disposed) { own.slots[index] = typeof value === "function" ? value(own.slots[index]) : value; own.dirty = true; } }]; }, useRef(initial) { if (!hooks) return React.useRef(initial); const index = hooks.index++; if (!(index in hooks.slots)) hooks.slots[index] = { current: initial }; return hooks.slots[index]; }, useCallback(callback, deps) { if (!hooks) return React.useCallback(callback, deps); const index = hooks.index++; if (!same(hooks.slots[index]?.deps, deps)) hooks.slots[index] = { callback, deps }; return hooks.slots[index].callback; }, useEffect(effect, deps) { if (!hooks) return React.useEffect(effect, deps); const own = hooks, index = own.index++; if (!same(own.slots[index]?.deps, deps)) { const before = own.slots[index], next = { deps, cleanup: before?.cleanup }; own.slots[index] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); } } };
const modules = new Map();
// This harness drives ProjectWork's hooks only. The independent fulfillment
// child has its own actual event suite in commitment-fulfillment.test.mjs.
function load(filename) { if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) }; if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync); if (modules.has(filename)) return modules.get(filename).exports; const loaded = new Module(filename); modules.set(filename, loaded); loaded.require = name => name === "react" ? react : name === "./commitment-fulfillment" ? { CommitmentFulfillment: () => null } : name === "./external-waits" ? { ExternalWaits: () => null } : name === "./project-risks" ? { ProjectRisks: () => null } : name === "@/components/ui/button" ? { Button: props => React.createElement("button", props) } : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(root, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name); loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename); return loaded.exports; }
const { RunContinuation } = load(path.join(directory,"run-continuation.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const run={run_id:id(1),session_id:"session-1",goal:"原目标",status:"completed",reverted:false};
const reading={run_id:id(1),owner_id:id(2),can_continue:true,existing:null};
const nodes=(tree,predicate)=>!tree||typeof tree!=="object"?[]:Array.isArray(tree)?tree.flatMap(v=>nodes(v,predicate)):tree.type?.name==="PaiComposer"?nodes(tree.type(tree.props),predicate):[...(predicate(tree)?[tree]:[]),...nodes(tree.props?.children,predicate)];
const words=tree=>typeof tree==="string"?tree:Array.isArray(tree)?tree.map(words).join(""):tree&&typeof tree==="object"?words(tree.props?.children):"";
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function environment(t, overrides = {}){const before=globalThis.localStorage,store=new Map();globalThis.localStorage={getItem:key=>store.get(key)??null,setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)};const calls=[],api=(route,body)=>new Promise((resolve,reject)=>calls.push({route,body,resolve,reject,done:false}));const state={slots:[],index:0,effects:[],dirty:false,disposed:false};let tree,unavailable=0;const props={api,root:"v1/agent-runs",run,principalId:id(2),contextText:"PRIVATE_PAGE_DRAFT",onUnavailable:()=>unavailable++,onOpen:async()=>{},...overrides};
function render(){state.index=0;state.effects=[];state.dirty=false;hooks=state;try{tree=RunContinuation(props)}finally{hooks=null}state.effects.forEach(effect=>effect())}render();if(overrides.strictMount)state.effects.forEach(effect=>effect());t.after(()=>{state.slots.forEach(slot=>slot?.cleanup?.());state.disposed=true;globalThis.localStorage=before});return {tree:()=>tree,html:()=>renderToStaticMarkup(tree),store,calls,unavailable:()=>unavailable,pending:()=>calls.find(call=>!call.done),respond(call,value){assert.ok(call);call.done=true;call.resolve(value)},reject(call,error){assert.ok(call);call.done=true;call.reject(error)},async flush(){for(let n=0;n<8;n++){await tick();if(state.dirty&&!state.disposed)render()}}};}
async function click(env,label){const node=nodes(env.tree(),node=>words(node.props?.children)===label&&typeof node.props?.onClick==="function")[0];assert.ok(node,label);node.props.onClick();await env.flush()}
async function prepare(env){await click(env,"读取后续记录");env.respond(env.pending(),reading);await env.flush();nodes(env.tree(),node=>node.type==="textarea")[0].props.onChange({target:{value:"继续完善"}});await env.flush();nodes(env.tree(),node=>node.type==="form")[0].props.onSubmit({preventDefault(){}});await env.flush();env.respond(env.pending(),reading);await env.flush();return env.pending()}
for(const status of [401,403]) test(`continuation ${status} clears page draft, original request and storage`,async t=>{const env=environment(t);const write=await prepare(env);assert.match(write.body.goal,/PRIVATE_PAGE_DRAFT/);assert.equal(env.store.size,1);env.reject(write,Object.assign(new Error("当前不可读"),{status}));await env.flush();assert.equal(env.store.size,0);assert.equal(env.unavailable(),1);assert.doesNotMatch(env.html(),/PRIVATE_PAGE_DRAFT|继续完善|核对并重试原请求|原目标/)});
test("an unknown continuation keeps and replays the original material snapshot",async t=>{const env=environment(t);const write=await prepare(env);env.reject(write,new Error("连接中断"));await env.flush();assert.match(env.html(),/核对并重试原请求/);await click(env,"核对并重试原请求");env.respond(env.pending(),reading);await env.flush();assert.deepEqual(env.pending().body,write.body)});

test("chat composer reads eligibility without sending, then continues the exact original run", async t => {
 const opened=[];const env=environment(t,{presentation:"composer",contextLabel:"噪声 · v2",onOpen:async id=>opened.push(id)});await env.flush();
 assert.equal(env.calls.length,1);assert.equal(env.pending().body,undefined);assert.match(env.pending().route,/\/continuation$/);
 env.respond(env.pending(),reading);await env.flush();
 assert.equal(nodes(env.tree(),n=>n.type==="textarea").length,1);assert.doesNotMatch(env.html(),/基于这次工作继续|发起新工作/);assert.match(env.html(),/噪声 · v2/);
 nodes(env.tree(),n=>n.type==="textarea")[0].props.onChange({target:{value:"继续完善验收口径"}});await env.flush();
 nodes(env.tree(),n=>n.type==="form")[0].props.onSubmit({preventDefault(){}});await env.flush();
 env.respond(env.pending(),reading);await env.flush();const write=env.pending();assert.equal(write.body.continue_from_run_id,run.run_id);assert.match(write.body.goal,/PRIVATE_PAGE_DRAFT/);
 env.respond(write,{run_id:id(3),continued_from_id:run.run_id});await env.flush();assert.deepEqual(opened,[id(3)]);
});
test("chat composer includes explicitly selected additional fixed sources", async t => {
 const env=environment(t,{presentation:"composer",additionalSources:[{artifact_id:id(9),expected_revision:2}]});await env.flush();
 env.respond(env.pending(),reading);await env.flush();
 nodes(env.tree(),n=>n.type==="textarea")[0].props.onChange({target:{value:"补充一份当前来源"}});await env.flush();
 nodes(env.tree(),n=>n.type==="form")[0].props.onSubmit({preventDefault(){}});await env.flush();
 env.respond(env.pending(),reading);await env.flush();
 assert.deepEqual(env.pending().body.sources,[{artifact_id:id(9),expected_revision:2}]);
});
test("a running conversation leaves a single disabled composer and makes no continuation call",async t=>{
 const env=environment(t,{presentation:"composer",run:{...run,status:"running"}});await env.flush();assert.equal(env.calls.length,0);assert.equal(nodes(env.tree(),n=>n.type==="textarea")[0].props.disabled,true);
});
test("chat composer permission failure removes the draft without a write",async t=>{
 const env=environment(t,{presentation:"composer"});await env.flush();env.reject(env.pending(),Object.assign(new Error("已撤销访问"),{status:403}));await env.flush();assert.equal(env.unavailable(),1);assert.equal(nodes(env.tree(),n=>n.type==="textarea").length,0);assert.equal(env.calls.every(call=>call.body===undefined),true);
});

test("chat composer stays usable after development effect cleanup and replay", async t => {
 const env=environment(t,{presentation:"composer",strictMount:true});await env.flush();
 assert.equal(env.calls.length,1);env.respond(env.pending(),reading);await env.flush();
 assert.equal(nodes(env.tree(),n=>n.type==="textarea")[0].props.disabled,false);
});
test("chat composer opens an existing continuation without sending again", async t => {
 const opened=[];const env=environment(t,{presentation:"composer",onOpen:async id=>opened.push(id)});await env.flush();
 env.respond(env.pending(),{...reading,can_continue:false,existing:{run_id:id(3),goal:"后续目标",idempotency_key:id(4)}});await env.flush();
 await click(env,"打开已保存的后续工作");assert.deepEqual(opened,[id(3)]);assert.equal(env.calls.length,1);assert.equal(env.calls[0].body,undefined);
});


test("running composer swaps send for an accessible non-submit stop control", async t => {
 let stopped=0; const env=environment(t,{presentation:"composer",run:{...run,status:"running"},onStop:()=>{stopped++;}}); await env.flush();
 const stop=nodes(env.tree(),n=>n.props?.["aria-label"]==="停止回复")[0];
 assert.equal(stop.props.type,"button");assert.equal(stop.props.disabled,false);
 assert.equal(nodes(env.tree(),n=>n.props?.["aria-label"]==="发送消息").length,0);
 stop.props.onClick();await env.flush();assert.equal(stopped,1);assert.equal(env.calls.length,0);
});
test("terminal runs do not offer stop even with a stale handler", async t => {
 const env=environment(t,{presentation:"composer",run:{...run,status:"completed"},onStop:()=>{throw Error("terminal must not cancel");}});await env.flush();
 assert.equal(nodes(env.tree(),n=>n.props?.["aria-label"]==="停止回复").length,0);
 assert.equal(nodes(env.tree(),n=>n.props?.["aria-label"]==="发送消息").length,1);
});
