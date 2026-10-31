import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
let hooks = null;
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Test-only state/effect dispatcher; SSR delegates unchanged. */
const reactShim = { ...React,
  useState(initial) {
    if (!hooks) return React.useState(initial);
    const own = hooks, index = own.index++;
    if (!(index in own.values)) own.values[index] = typeof initial === "function" ? initial() : initial;
    return [own.values[index], value => { own.values[index] = typeof value === "function" ? value(own.values[index]) : value; }];
  },
  useRef(initial) {
    if (!hooks) return React.useRef(initial);
    const index = hooks.index++;
    if (!(index in hooks.values)) hooks.values[index] = { current: initial };
    return hooks.values[index];
  },
  useMemo(callback, dependencies) { return hooks ? callback() : React.useMemo(callback, dependencies); },
  useCallback(callback, dependencies) { return hooks ? callback : React.useCallback(callback, dependencies); },
  useEffect(callback, dependencies) { if (!hooks) React.useEffect(callback, dependencies); else hooks.effects.push(callback); },
};
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule:true, default:new Proxy({}, {get:(_,key)=>String(key)}) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? reactShim
    : specifier === "@phosphor-icons/react" ? Object.fromEntries(["ArrowClockwise", "Check", "CaretRight", "X"].map(key => [key, () => React.createElement("svg")]))
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { fileName:filename, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}

const { ProjectGovernance } = load(path.join(directory,"project-governance.tsx"));
const fields={categoryId:"11111111-1111-4111-8111-111111111111",productId:"22222222-2222-4222-8222-222222222222",projectId:"33333333-3333-4333-8333-333333333333",principalId:"44444444-4444-4444-8444-444444444444"};
const gate={stage_id:null,state:"UNKNOWN",checks:[],maturity:{engineering:{state:"UNKNOWN",detail:"unknown"},manufacturing:{state:"UNKNOWN",detail:"unknown"},delivery:{state:"UNKNOWN",detail:"unknown"}},required_source_read_set:[]};
const data={project_id:fields.projectId,product_revision:1,project_revision:1,revision:0,template:null,stages:[],current_stage:null,completed:false,gate,next_gate:null,health:{label:"待核对",reason:"尚未采用"},timeline:{task_key:null,baseline:null,forecast:null,commitments:[],actual:null},can_manage:true,templates:[{id:"standard@1",name:"完整开发",stages:[]}],plan:null,history:[],release_packages:[],release_packages_cursor:null};
function elements(tree,predicate){if(!tree||typeof tree!=="object")return [];if(Array.isArray(tree))return tree.flatMap(v=>elements(v,predicate));return [...(predicate(tree)?[tree]:[]),...elements(tree.props?.children,predicate)];}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function mounted(api,callback,broken=false){
 const original=globalThis.localStorage;const entries=new Map();
 globalThis.localStorage={getItem:k=>entries.get(k)??null,setItem:(k,v)=>{if(broken)throw Error("quota");entries.set(k,v);}};
 const state={index:0,values:[],effects:[]};
 const render=()=>{hooks=state;state.index=0;state.effects=[];try{return ProjectGovernance({...fields,api});}finally{hooks=null;}};
 try{render();state.effects.forEach(f=>f());await tick();await callback(render,entries);}finally{globalThis.localStorage=original;}
}
for(const status of [undefined,409])test(`failed stage confirmation ${status??"network"} releases modal and retains exact request for retry`,async()=>{
 const writes=[];let fail=true;
 await mounted(async(path,body)=>{
  if(!body)return structuredClone(data);
  writes.push({path,body});
  if(path.endsWith("preview"))return {command:{...body,payload:{...body.payload,confirmation_token:"fixed-token"}},review:{operation:body.operation,name:"Synthetic",reason:body.payload.reason,effect:"Synthetic stage adoption"}};
  if(fail){fail=false;throw Object.assign(Error("synthetic failure"),{status});}
  return {id:"receipt",subject_type:"project_governance"};
 },async(render,entries)=>{
  elements(render(),e=>e.type==="textarea")[0].props.onChange({target:{value:"synthetic reason"}});
  await elements(render(),e=>e.props?.children==="核对并采用模板")[0].props.onClick();await tick();
  const confirm=elements(render(),e=>e.props?.children==="确认办理")[0];assert.ok(confirm);await confirm.props.onClick();await tick();
  let tree=render();assert.equal(elements(tree,e=>e.type?.name==="DetailSheet").length,0);
  const retry=elements(tree,e=>e.props?.children==="按原请求重试")[0];assert.ok(retry);assert.equal(retry.props.disabled,false);
  const cached=JSON.parse([...entries.values()][0]);assert.equal(cached.pending.stage,"execute");
  await retry.props.onClick();await tick();assert.deepEqual(writes[2].body,writes[1].body);assert.equal(JSON.parse([...entries.values()][0]).pending,null);
 });
});
test("stage storage failure prevents every network command",async()=>{
 const writes=[];await mounted(async(path,body)=>{if(body)writes.push(body);return structuredClone(data);},async(render)=>{
  elements(render(),e=>e.type==="textarea")[0].props.onChange({target:{value:"synthetic reason"}});
  await elements(render(),e=>e.props?.children==="核对并采用模板")[0].props.onClick();await tick();
  assert.equal(writes.length,0);assert.ok(elements(render(),e=>e.props?.role==="alert"&&e.props.children.includes("尚未提交")).length);
 },true);
});
