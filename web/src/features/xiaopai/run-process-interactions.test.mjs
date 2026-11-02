import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const directory = path.dirname(fileURLToPath(import.meta.url)), root = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(root, "package.json")), ts = dependency("typescript"), React = dependency("react");
let hooks;
const same = (a,b) => a && b && a.length === b.length && a.every((item,i) => Object.is(item,b[i]));
const shim = {...React,
 useState(initial) {const own=hooks,index=own.index++;if(!(index in own.values))own.values[index]=typeof initial==="function"?initial():initial;return [own.values[index],value=>{own.values[index]=typeof value==="function"?value(own.values[index]):value;}];},
 useRef(initial) {const index=hooks.index++;return hooks.values[index]??={current:initial};},
 useEffect(effect,deps) {const own=hooks,index=own.index++,old=own.values[index];if(!old||!same(old.deps,deps))own.effects.push(()=>{old?.cleanup?.();own.values[index]={deps,cleanup:effect()};});},
};
const cache=new Map();
function load(filename) {
 if(filename.endsWith(".css"))return {__esModule:true,default:{}};
 if(!path.extname(filename))filename=[".tsx",".ts"].map(ext=>filename+ext).find(existsSync);
 if(cache.has(filename))return cache.get(filename).exports;
 const loaded=new Module(filename);cache.set(filename,loaded);
 loaded.require=name=>name==="react"?shim:name==="@phosphor-icons/react"?new Proxy({},{get:()=>()=>React.createElement("svg")}):name.startsWith("@/")?load(path.join(root,"src",name.slice(2))):name.startsWith(".")?load(path.resolve(path.dirname(filename),name)):dependency(name);
 loaded._compile(ts.transpileModule(readFileSync(filename,"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,filename);
 return loaded.exports;
}
const {RunProcess}=load(path.join(directory,"run-process.tsx"));
const nodes=tree=>!tree||typeof tree!=="object"?[]:Array.isArray(tree)?tree.flatMap(nodes):[tree,...nodes(tree.props?.children)];
const text=tree=>typeof tree==="string"||typeof tree==="number"?String(tree):Array.isArray(tree)?tree.map(text).join(""):tree&&typeof tree==="object"?text(tree.props?.children):"";
const event=sequence=>({id:`actual-event-${sequence}`,sequence,kind:"context_observed",at:"2026-10-29T00:01:00Z",tool:null,skill:null,version:null,status:null,context_metrics:{version:1,history:{carried:sequence},warnings:[]}});
const original={run_id:"11111111-1111-4111-8111-111111111111",status:"partial",reverted:false,error_code:null,started_at:"2026-10-29T00:00:00Z",observed_at:"2026-10-29T00:01:00Z",last_recorded_at:null,ended_at:null,elapsed_seconds:null,call_counts:{total:1,completed:1,pending:0,failed:0},source_count:1,business_receipt_count:1,sources:[{id:"source",title:"actual private filename",bound_revision:1,current_revision:1}],receipts:[{id:"receipt",operation:"record",subject_revision:1}],steps:[event(5)],next_before:5,next_source_cursor:"22222222-2222-4222-8222-222222222222",next_receipt_cursor:"33333333-3333-4333-8333-333333333333"};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function runner(api) {
 const own={index:0,values:[],effects:[]},props={value:structuredClone(original),api,root:"v1/agent-runs",onUnavailable:()=>{own.unavailable++;}};own.unavailable=0;
 return {own,props,render(){hooks=own;own.index=0;own.effects=[];let tree;try{tree=RunProcess(props);}finally{hooks=null;}own.effects.forEach(effect=>effect());return tree;},async click(label){const button=nodes(this.render()).find(node=>node.props?.onClick&&text(node.props.children)===label);assert.ok(button,label);button.props.onClick();for(let i=0;i<4;i++)await tick();return this.render();},metrics(){return nodes(this.render()).find(node=>typeof node.type==="function"&&node.type.name==="ContextMetricsDetails");},unmount(){own.values.forEach(value=>value?.cleanup?.());}};
}
test("reading earlier metrics uses the original GET cursor once without a model or write",async()=>{
 const calls=[];const r=runner(async(path,body)=>{calls.push({path,body});return {...original,steps:[event(2)],next_before:null};});
 try{assert.ok(r.metrics());assert.equal(calls.length,0);await r.click("读取更早步骤");assert.equal(calls.length,1);assert.equal(calls[0].path,`v1/agent-runs/${original.run_id}/process?before=5`);assert.equal(calls[0].body,undefined);assert.deepEqual(r.metrics().props.steps.map(step=>step.sequence),[2,5]);}finally{r.unmount();}
});
for(const status of [401,403,404])test(`a ${status} process denial removes loaded metrics and retained source metadata`,async()=>{
 let deny=false;const calls=[];const r=runner(async(path,body)=>{calls.push({path,body});if(deny)throw Object.assign(Error("current authority unavailable"),{status});return {...original,steps:[event(2)],sources:[{id:"extra-source",title:"PRIVATE EXTRA",bound_revision:1,current_revision:1}],next_before:2,next_source_cursor:null};});
 try{await r.click("读取更早步骤");await r.click("更多绑定依据");assert.ok(text(r.render()).includes("PRIVATE EXTRA"));deny=true;await r.click("读取更早步骤");assert.match(text(r.render()),/当前无权读取处理过程/);assert.equal(r.metrics(),undefined);assert.equal(r.own.unavailable,1);assert.ok(calls.every(call=>call.body===undefined));
 r.props.value={...original,observed_at:"2026-10-29T00:02:00Z"};assert.deepEqual(r.metrics().props.steps.map(step=>step.sequence),[5]);assert.ok(!text(r.render()).includes("PRIVATE EXTRA"));}finally{r.unmount();}
});
for(const status of [401,403,404])test(`a ${status} source-page denial hides metric details as part of the same original Run view`,async()=>{
 const r=runner(async()=>{throw Object.assign(Error("current authority unavailable"),{status});});
 try{await r.click("更多绑定依据");assert.equal(r.metrics(),undefined);assert.match(text(r.render()),/当前无权读取处理过程/);assert.equal(r.own.unavailable,1);}finally{r.unmount();}
});
test("late earlier-page response after unmount cannot introduce another Run's context",async()=>{
 let resolve;const r=runner(()=>new Promise(done=>{resolve=done;}));
 const reading=r.click("读取更早步骤");r.unmount();resolve({...original,steps:[event(1)],next_before:null});await reading;
 assert.deepEqual(r.metrics().props.steps.map(step=>step.sequence),[5]);
});
