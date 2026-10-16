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
