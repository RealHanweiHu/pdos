import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), root = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(root, "package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks;
const same = (a,b) => !!a && !!b && a.length === b.length && a.every((v,i) => Object.is(v,b[i]));
const react = { ...React,
  useState(initial) { const own=hooks, i=own.index++; if(!(i in own.slots))own.slots[i]=typeof initial==="function"?initial():initial; return [own.slots[i],next=>{own.slots[i]=typeof next==="function"?next(own.slots[i]):next;own.dirty=true;}]; },
  useRef(initial) { const i=hooks.index++; return hooks.slots[i]??=( {current:initial} ); },
  useEffect(effect,deps) { const own=hooks,i=own.index++;if(!same(own.slots[i]?.deps,deps)){const previous=own.slots[i];own.slots[i]={deps,cleanup:previous?.cleanup};own.effects.push(()=>{previous?.cleanup?.();own.slots[i].cleanup=effect();});} },
};
const cache=new Map();
function load(file) {
  if(file.endsWith(".css"))return {__esModule:true,default:new Proxy({},{get:(_,key)=>key})};
  if(!path.extname(file))file=[".ts",".tsx"].map(ext=>file+ext).find(existsSync);
  if(cache.has(file))return cache.get(file).exports;
  const mod=new Module(file);cache.set(file,mod);
  mod.require=name=>name==="react"?react:name==="@phosphor-icons/react"?new Proxy({},{get:()=>()=>React.createElement("svg")}):name==="@/components/ui/button"?{Button:props=>React.createElement("button",props)}:name.startsWith("@/")?load(path.join(root,"src",name.slice(2))):name.startsWith(".")?load(path.resolve(path.dirname(file),name)):dependency(name);
  mod._compile(ts.transpileModule(readFileSync(file,"utf8"),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,file);
  return mod.exports;
}
const {ProjectProfessionalRecords}=load(path.join(directory,"project-professional-records.tsx"));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function environment(t, initial={}) {
  const calls=[], own={slots:[],index:0,effects:[],dirty:true};
  let props={api:(route,body)=>new Promise((resolve,reject)=>calls.push({route,body,resolve,reject,done:false})),productId:"p",projectId:"project",panel:"results",readVersion:0,onEdit:()=>{},...initial},tree;
  function render(){own.index=0;own.effects=[];own.dirty=false;hooks=own;tree=ProjectProfessionalRecords(props);hooks=null;own.effects.forEach(effect=>effect());}
  render();t.after(()=>own.slots.forEach(slot=>slot?.cleanup?.()));
  return {calls,tree:()=>tree,html:()=>renderToStaticMarkup(tree),setProps(next){props={...props,...next};render();},pending(fragment){return calls.find(call=>!call.done&&call.route.includes(fragment));},respond(call,value){assert.ok(call);call.done=true;call.resolve(value);},async flush(){for(let i=0;i<8;i++){await tick();if(own.dirty)render();}}};
}
const builds={items:[{id:"b",name:"Selected Build",project_id:"project"}]};
const results=title=>({runs:[{id:title,run_id:"run",request_id:"request",build:{id:"b",project_id:"project"},is_current:true,title,status:"disposed"}]});
async function ready(env){await env.flush();env.respond(env.pending("/builds?"),builds);await env.flush();if(env.pending("/builds?")){env.respond(env.pending("/builds?"),builds);await env.flush();}env.respond(env.pending("verification-results"),results("Saved result"));await env.flush();}

test("continuing an already displayed auto-selected Build does not leave its records loading forever",async t=>{
  const env=environment(t);await ready(env);assert.match(env.html(),/Saved result/);
  env.setProps({initialBuild:"b"});await env.flush();
  assert.match(env.html(),/Saved result/);assert.doesNotMatch(env.html(),/正在读取专业记录/);assert.ok(env.calls.every(call=>call.body===undefined));
});
test("unreadable deep-linked Build remains an explicit error instead of adopting another Build",async t=>{
  const env=environment(t,{initialBuild:"foreign"});await env.flush();env.respond(env.pending("/builds?"),builds);await env.flush();
  assert.match(env.html(),/指定轮次不在本项目当前可读范围/);assert.equal(env.calls.length,1);
});
test("late reads from an earlier refresh cannot replace current records",async t=>{
  const env=environment(t,{initialBuild:"b"});await env.flush();env.respond(env.pending("/builds?"),builds);await env.flush();const old=env.pending("verification-results");
  env.setProps({readVersion:1});await env.flush();env.respond(env.pending("/builds?"),builds);await env.flush();
  const fresh=env.calls.filter(call=>call.route.includes("verification-results"))[1];env.respond(fresh,results("Current record"));await env.flush();env.respond(old,results("Stale record"));await env.flush();
  assert.match(env.html(),/Current record/);assert.doesNotMatch(env.html(),/Stale record/);
});

const nodes=tree=>!tree||typeof tree!=="object"?[]:Array.isArray(tree)?tree.flatMap(nodes):[tree,...nodes(tree.props?.children)];
for(const panel of ["quality","followup"])test(`${panel} actual row detail mounts history using that exact fixed issue version`,async t=>{
  const old=globalThis.requestAnimationFrame;globalThis.requestAnimationFrame=callback=>callback();t.after(()=>{if(old)globalThis.requestAnimationFrame=old;else delete globalThis.requestAnimationFrame;});
  const env=environment(t,{panel,initialBuild:"b"});await env.flush();env.respond(env.pending("/builds?"),builds);await env.flush();
  env.respond(env.pending("quality-execution"),{issues:[{id:"fixed-issue-version",issue_id:"logical-issue",project_id:"project",revision:3,source_status:"current",is_current:true,issue:{title:"接口漏气",status:"open"}}]});await env.flush();
  const trigger=nodes(env.tree()).find(node=>node.type==="button"&&node.props["aria-controls"]===`professional-record-detail-${panel}`);assert.ok(trigger);trigger.props.onClick({currentTarget:{}});await env.flush();
  const {SimilarHistory,SimilarHistoryLayout}=load(path.join(root,"src/components/similar-history.tsx"));
  const layout=nodes(env.tree()).find(node=>node.type===SimilarHistoryLayout);assert.ok(layout,"actual row detail has history layout");
  assert.equal(layout.props.history.type,SimilarHistory);assert.equal(layout.props.history.props.issueId,"logical-issue");assert.equal(layout.props.history.props.versionId,"fixed-issue-version");assert.equal(layout.props.history.props.productId,"p");
  assert.ok(env.calls.every(call=>call.body===undefined),"opening row detail never writes");
});

test("change row detail mounts the selected historical version without merge or creation callbacks",async t=>{
  const old=globalThis.requestAnimationFrame;globalThis.requestAnimationFrame=callback=>callback();t.after(()=>{if(old)globalThis.requestAnimationFrame=old;else delete globalThis.requestAnimationFrame;});
  const env=environment(t,{panel:"changes"});await env.flush();
  env.respond(env.pending("change-execution?project_id="),{changes:[{id:"fixed-change-version",change_id:"logical-change",project_id:"project",revision:2,source_status:"current",current:false,request:{title:"历史变更",status:"analysis"}}]});await env.flush();
  const history=nodes(env.tree()).find(node=>node.type==="input"&&node.props.type==="checkbox");history.props.onChange({target:{checked:true}});await env.flush();
  const trigger=nodes(env.tree()).find(node=>node.type==="button"&&node.props["aria-controls"]==="professional-record-detail-changes");assert.ok(trigger);trigger.props.onClick({currentTarget:{}});await env.flush();
  const {SimilarHistory,SimilarHistoryLayout}=load(path.join(root,"src/components/similar-history.tsx"));
  const layout=nodes(env.tree()).find(node=>node.type===SimilarHistoryLayout);assert.equal(layout.props.history.type,SimilarHistory);
  assert.equal(layout.props.history.props.changeId,"logical-change");assert.equal(layout.props.history.props.versionId,"fixed-change-version");
  assert.equal(layout.props.history.props.issueId,undefined);assert.equal(layout.props.history.props.onMerge,undefined);
  assert.ok(env.calls.every(call=>call.body===undefined));
});
