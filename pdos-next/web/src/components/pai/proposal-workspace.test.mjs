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
const react = { ...React, useState(initial) { const own = hooks, index = own.index++; if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial; return [own.slots[index], value => { if (!own.disposed) { own.slots[index] = typeof value === "function" ? value(own.slots[index]) : value; own.dirty = true; } }]; }, useRef(initial) { const index = hooks.index++; if (!(index in hooks.slots)) hooks.slots[index] = { current: initial }; return hooks.slots[index]; }, useCallback(callback, deps) { const index = hooks.index++; if (!same(hooks.slots[index]?.deps, deps)) hooks.slots[index] = { callback, deps }; return hooks.slots[index].callback; }, useEffect(effect, deps) { const own = hooks, index = own.index++; if (!same(own.slots[index]?.deps, deps)) { const before = own.slots[index], next = { deps, cleanup: before?.cleanup }; own.slots[index] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); } } };
let transport;
const modules = new Map();
// This harness drives ProjectWork's hooks only. The independent fulfillment
// child has its own actual event suite in commitment-fulfillment.test.mjs.
function load(filename) { if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) }; if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync); if (modules.has(filename)) return modules.get(filename).exports; const loaded = new Module(filename); modules.set(filename, loaded); loaded.require = name => name === "react" ? react : name === "@/lib/browser-api" ? {browserApi: (...args)=>transport(...args)} : name === "@/components/preproject/proposal-document" ? {ProposalDocument: props=>React.createElement("div",{"data-saved":props.proposalId},"saved document")} : name === "@/components/preproject/proposal-spec-editor" ? {ProposalSpecEditor: ()=>null} : name === "@/components/preproject/proposal-item-table" ? {ProposalItemTable:()=>null} : name === "./commitment-fulfillment" ? { CommitmentFulfillment: () => null } : name === "./external-waits" ? { ExternalWaits: () => null } : name === "./project-risks" ? { ProjectRisks: () => null } : name === "@/components/ui/button" ? { Button: props => React.createElement("button", props) } : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(root, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name); loaded._compile(ts.transpileModule(readFileSync(filename, "utf8").replace("function MaterialForm(", "export function MaterialForm("), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename); return loaded.exports; }

const {PaiProposalWorkspace}=load(path.join(directory,"proposal-workspace.tsx"));
const id=n=>`00000000-0000-4000-8000-${String(n).padStart(12,"0")}`;
const category=id(1),principal=id(2),command={command_id:id(3),idempotency_key:id(4),category_id:category,product_id:null,operation:"proposal.create",expected_revision:1,source_read_set:[],payload:{title:"AI 原提案",brief:"AI 原摘要",groups:{items:[],questions:[]},prepared_by_run_id:id(5),candidate_digest:"a".repeat(64)}};
const candidate={event_id:id(6),sequence:1,state:"pending",command,operation:command.operation,receipt:null};
const nodes=(tree,predicate)=>!tree||typeof tree!=="object"?[]:Array.isArray(tree)?tree.flatMap(item=>nodes(item,predicate)):[...(predicate(tree)?[tree]:[]),...nodes(tree.props?.children,predicate)];
const words=tree=>typeof tree==="string"?tree:Array.isArray(tree)?tree.map(words).join(""):tree&&typeof tree==="object"?words(tree.props?.children):"";
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function env(t,changes={},store=new Map()){
 const before=globalThis.sessionStorage,beforeWindow=globalThis.window;const storage={fail:false,getItem:key=>store.get(key)??null,setItem(key,value){if(this.fail)throw Error("storage denied");store.set(key,value)},removeItem:key=>store.delete(key)};globalThis.sessionStorage=storage;globalThis.window={dispatchEvent(){}};
 const calls=[],contexts=[];transport=(route,body)=>new Promise((resolve,reject)=>calls.push({route,body,resolve,reject,done:false}));
 const props={candidate,categoryId:category,principalId:principal,open:true,onClose(){},onSaved(){},onUnavailable(){},onContextChange:(id,context)=>contexts.push(context),...changes};const state={slots:[],index:0,effects:[],dirty:false,disposed:false};let tree;
 function render(){hooks=state;state.index=0;state.effects=[];state.dirty=false;try{tree=PaiProposalWorkspace(props)}finally{hooks=null}state.effects.forEach(effect=>effect())}
 function dispose(){state.slots.forEach(slot=>slot?.cleanup?.());state.disposed=true}
 render();t.after(()=>{dispose();globalThis.sessionStorage=before;globalThis.window=beforeWindow});
 return {calls,contexts,store,storage,dispose,tree:()=>tree,html:()=>renderToStaticMarkup(tree),pending:part=>calls.find(call=>!call.done&&call.route.includes(part)),reply(call,value){assert.ok(call);call.done=true;call.resolve(value)},reject(call,error){assert.ok(call);call.done=true;call.reject(error)},async flush(){for(let i=0;i<8;i++){await tick();if(state.dirty&&!state.disposed)render()}}};
}
async function click(e,label){const button=nodes(e.tree(),item=>typeof item.props?.onClick==="function"&&words(item.props.children)===label)[0];assert.ok(button,label);assert.ok(!button.props.disabled,label);button.props.onClick();await e.flush()}
async function fill(e,value){nodes(e.tree(),item=>item.props?.["aria-label"]==="提案名称")[0].props.onChange({target:{value}});await e.flush()}
async function ready(e){await e.flush();e.reply(e.pending("/participants"),{items:[]});await e.flush()}
async function prepare(e){await fill(e,"本人修订的提案");await click(e,"保存提案");const request=e.pending("/preview");e.reply(request,{command:{...request.body,payload:{...request.body.payload,confirmation_token:"confirmed-proposal-save-token"}},expires_at:"2099-01-01T00:00:00Z",review:{}});await e.flush();return request.body}
test("human edits remain separate from the original, save keeps the workspace and opens the same document",async t=>{
 let closes=0,saved=0;const e=env(t,{onClose:()=>closes++,onSaved:()=>saved++});await ready(e);const req=await prepare(e);assert.equal(req.payload.title,"AI 原提案");assert.equal(req.payload.human_edits.title,"本人修订的提案");await click(e,"确认保存");const save=e.pending("/commands");e.reply(save,{id:id(7),subject_type:"proposal",subject_id:id(8),operation:command.operation,result:{}});await e.flush();assert.equal(closes,0);assert.equal(saved,1);assert.match(e.html(),new RegExp(`data-saved="${id(8)}"`));assert.equal(e.store.size,0);
});
test("unknown writes restore the edited content and replay exactly without automatic resubmission",async t=>{
 const store=new Map(),first=env(t,{},store);await ready(first);await prepare(first);await click(first,"确认保存");const save=first.pending("/commands");first.reject(save,Error("offline"));await first.flush();first.dispose();const second=env(t,{},store);await ready(second);assert.match(second.html(),/本人修订的提案/);assert.equal(second.calls.some(call=>call.body),false);await click(second,"核对原请求");assert.deepEqual(second.pending("/commands").body,save.body);
});
test("storage failure prevents a write; a mismatched preview never enables confirmation",async t=>{
 const e=env(t);await ready(e);await prepare(e);e.storage.fail=true;await click(e,"确认保存");assert.equal(e.calls.some(call=>call.route.endsWith("/commands")),false);assert.match(e.html(),/本机存储失败/);
});
test("permission loss clears document and context even if the parent has not yet unmounted",async t=>{
 let denied=0;const e=env(t,{onUnavailable:()=>denied++});await ready(e);await prepare(e);await click(e,"确认保存");e.reject(e.pending("/commands"),Object.assign(Error("permission revoked"),{status:403}));await e.flush();assert.equal(denied,1);assert.equal(e.store.size,0);assert.doesNotMatch(e.html(),/本人修订的提案|AI 原摘要/);assert.equal(e.contexts.at(-1),undefined);
});
test("a forged preview cannot replace the sealed source or human edits",async t=>{
 const e=env(t);await ready(e);await fill(e,"修订");await click(e,"保存提案");const request=e.pending("/preview");e.reply(request,{command:{...request.body,payload:{...request.body.payload,title:"changed original",confirmation_token:"confirmed-proposal-save-token"}},expires_at:"2099-01-01T00:00:00Z",review:{}});await e.flush();assert.match(e.html(),/无法核对/);assert.equal(nodes(e.tree(),item=>words(item.props?.children)==="确认保存").length,0);
});
