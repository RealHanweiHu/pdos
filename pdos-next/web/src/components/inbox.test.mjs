import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Isolated component state harness. */
const reactShim = { ...React, useState(initial) {
  if (!hooks) return React.useState(initial);
  const own = hooks, index = own.index++;
  if (!(index in own.values)) own.values[index] = typeof initial === "function" ? initial() : initial;
  return [own.values[index], next => { own.values[index] = typeof next === "function" ? next(own.values[index]) : next; }];
}, useRef(initial) { if (!hooks) return React.useRef(initial); const index = hooks.index++; return hooks.values[index] ??= { current: initial }; }, useCallback(callback, dependencies) {
  if (!hooks) return React.useCallback(callback, dependencies);
  const index = hooks.index++;
  if (!same(hooks.values[index]?.dependencies, dependencies)) hooks.values[index] = { callback, dependencies };
  return hooks.values[index].callback;
}, useEffect(callback, dependencies) {
  if (!hooks) return React.useEffect(callback, dependencies);
  const own = hooks, index = own.index++;
  if (!same(own.values[index]?.dependencies, dependencies)) { const previous = own.values[index]; const entry = { dependencies, cleanup: previous?.cleanup }; own.values[index] = entry; own.effects.push(() => { entry.cleanup?.(); entry.cleanup = callback(); }); }
} };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const cache = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? reactShim
    : specifier === "next/link" ? props => React.createElement("a", { href: props.href }, props.children)
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}

const { Inbox } = load(path.join(directory, "inbox.tsx"));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item,predicate));
  return [...(predicate(tree) ? [tree] : []),...elements(tree.props?.children,predicate)];
}
function label(tree) { if (tree==null||typeof tree==="boolean") return ""; if(typeof tree!=="object")return String(tree);if(Array.isArray(tree))return tree.map(label).join("");return label(tree.props?.children); }
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function driver(props) { const state={index:0,values:[],effects:[]};return { render(){ hooks=state;state.index=0;state.effects=[];try{const outer=Inbox(props);return outer.type(outer.props);}finally{hooks=null;}}, mount(){state.effects.forEach(effect=>effect());},unmount(){for(const value of state.values)value?.cleanup?.();} }; }
const button=(tree,text)=>elements(tree,node=>typeof node.props?.onClick==="function"&&(label(node)===text||node.props?.["aria-label"]===text))[0];
const field=(tree,name)=>elements(elements(tree,node=>node.type==="label"&&label(node).startsWith(name))[0],node=>["input","textarea","select"].includes(node.type))[0];
const me="00000000-0000-4000-8000-000000000001",peer="00000000-0000-4000-8000-000000000002",category="00000000-0000-4000-8000-000000000003",conversation="00000000-0000-4000-8000-000000000004";
function storage(){const values=new Map();globalThis.localStorage={getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value),removeItem:key=>values.delete(key)};return values;}
test("unknown message outcome preserves the exact original request for explicit retry",async()=>{
 const saved=storage(),sent=[];let failed=true;
 const api=async(path,body)=>{if(body){sent.push({path,body:structuredClone(body)});if(failed)throw Object.assign(new Error("transport"),{status:503});return {conversation_id:conversation};}if(path==="v1/categories")return [{id:category,name:"合成品类"}];if(path.endsWith("participants"))return {items:[{id:me,name:"我"},{id:peer,name:"同事"}]};if(path.endsWith("/messages"))return {conversation_id:conversation,items:[],next_before:null};return {items:[],next_cursor:null};};
 const app=driver({api,principalId:me,onOpenRun(){}});let tree=app.render();app.mount();await tick();tree=app.render();app.mount();await tick();tree=app.render();
 button(tree,"发起聊天").props.onClick();tree=app.render();app.mount();await tick();tree=app.render();
 const checkbox=elements(tree,node=>node.type==="input"&&node.props.type==="checkbox")[0];assert.ok(checkbox);checkbox.props.onChange({target:{checked:true}});
 field(tree,"标题").props.onChange({target:{value:"合成协作"}});field(tree,"消息").props.onChange({target:{value:"合成消息"}});tree=app.render();
 const form=elements(tree,node=>node.type==="form")[0];form.props.onSubmit({preventDefault(){}});await tick();tree=app.render();assert.equal(sent.length,1);assert.ok([...saved.values()][0].includes("合成消息"));assert.ok(button(tree,"按原请求重试"));
 failed=false;button(tree,"按原请求重试").props.onClick();await tick();app.render();assert.equal(sent.length,2);assert.deepEqual(sent[0],sent[1]);assert.equal(saved.size,0);app.unmount();
});
test("permission loss clears pending requests and hides message bodies",async()=>{
 const saved=storage();let fail=false;
 const api=async(path)=>{if(fail)throw Object.assign(new Error("revoked"),{status:403});if(path==="v1/categories")return [{id:category,name:"品类"}];if(path.endsWith("conversations"))return {items:[{id:conversation,title:"私有标题",category_id:category,category_name:"品类",members:[],latest:{sequence:1},created_at:"2026-10-25T00:00:00Z"}],next_cursor:null};if(path.endsWith("messages"))return {conversation_id:conversation,items:[{id:"m",sender_id:peer,sender_name:"同事",sequence:1,body:"私有正文",created_at:"2026-10-25T00:00:00Z"}],next_before:null};return {items:[],next_cursor:null};};
 const app=driver({api,principalId:me,onOpenRun(){}});let tree=app.render();app.mount();await tick();tree=app.render();button(tree,"聊天").props.onClick();tree=app.render();button(tree,"私有标题").props.onClick();await tick();tree=app.render();assert.ok(label(tree).includes("私有正文"));
 fail=true;elements(tree,node=>node.props?.["aria-label"]==="刷新收件箱")[0].props.onClick();await tick();tree=app.render();assert.ok(!label(tree).includes("私有正文"));assert.ok(!label(tree).includes("私有标题"));assert.equal(saved.size,0);app.unmount();
});

test("notifications exclude ordinary completed chats and keep requests needing attention",async()=>{
 storage();
 const waiting={run_id:"waiting",goal:"需要确认提案",status:"waiting_input",reading_token:"waiting_input:0",created_at:"2026-10-25T00:00:00Z",categoryName:"品类",categoryId:category};
 const api=async(path)=>{if(path==="v1/categories")return [];if(path.includes("run-activity"))return {items:path.includes("waiting=true")?[waiting]:[{...waiting,run_id:"ordinary",goal:"普通问候",status:"completed"},{...waiting,run_id:"failure",goal:"整理资料中断",status:"failed"}],next_cursor:null};return {items:[],next_cursor:null};};
 const app=driver({api,principalId:me,onOpenRun(){}});app.render();app.mount();await tick();const tree=app.render();assert.ok(label(tree).includes("需要确认提案"));assert.ok(label(tree).includes("整理资料中断"));assert.ok(!label(tree).includes("普通问候"));app.unmount();
});
test("switching conversations preserves independent unsent drafts",async()=>{
 storage(); const second="00000000-0000-4000-8000-000000000005";
 const api=async(path,body)=>{if(body)return {};if(path==="v1/categories")return [];if(path.endsWith("conversations"))return {items:[conversation,second].map((id,i)=>({id,title:`会话${i+1}`,category_name:"合成品类",members:[],created_at:"2026-10-25T00:00:00Z",latest:null})),next_cursor:null};if(path.endsWith("messages"))return {conversation_id:path.includes(second)?second:conversation,items:[],next_before:null};return {items:[],next_cursor:null};};
 const app=driver({api,principalId:me,onOpenRun(){}});app.render();app.mount();await tick();let tree=app.render();button(tree,"聊天").props.onClick();tree=app.render();button(tree,"会话1").props.onClick();await tick();tree=app.render();let reply=elements(tree,node=>node.type==="textarea"&&node.props.value==="")[0];assert.ok(reply);reply.props.onChange({target:{value:"尚未发送的第一份草稿"}});tree=app.render();button(tree,"会话2").props.onClick();await tick();tree=app.render();assert.equal(elements(tree,node=>node.type==="textarea")[0].props.value,"");button(tree,"会话1").props.onClick();await tick();tree=app.render();assert.equal(elements(tree,node=>node.type==="textarea")[0].props.value,"尚未发送的第一份草稿");app.unmount();
});
