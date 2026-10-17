import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Installed compiler only; no Next build, service, shared cache or external data.
const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(root, "package.json"));
const ts = dependency("typescript");
const React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const cache = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (!filename) throw new Error("Owned test module not found");
  if (cache.has(filename)) return cache.get(filename).exports;
  const mod = new Module(filename);
  cache.set(filename, mod);
  const requireLocal = createRequire(filename);
  mod.require = specifier => specifier.startsWith("@/") ? load(path.join(root, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : requireLocal(specifier);
  mod._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return mod.exports;
}
const {RunContinuation}=load(path.join(directory,"run-continuation.tsx"));
const props={api:()=>{throw new Error("Closed continuation cannot read or dispatch");},root:"v1/agent-runs",onOpen:()=>{throw new Error("No automatic navigation");},run:{run_id:"original",status:"completed",reverted:false,conversation:{previous_run_id:"previous",next_run_id:null}}};
test("终态显示继续工作与原记录入口，关闭时没有读取、派发或导航",()=>{
 const html=renderToStaticMarkup(React.createElement(RunContinuation,props));
 assert.match(html,/基于这次工作继续/);assert.match(html,/查看前一次工作/);
 assert.match(html,/事实与权限在继续前重新核对/);
});
test("未完成或已撤回运行不显示新继续表单，既有后续仍可查看",()=>{
 for(const run of [{...props.run,status:"waiting_input"},{...props.run,reverted:true}]){
  const html=renderToStaticMarkup(React.createElement(RunContinuation,{...props,run}));
  assert.ok(!html.includes("基于这次工作继续"));
 }
 const html=renderToStaticMarkup(React.createElement(RunContinuation,{...props,run:{...props.run,conversation:{previous_run_id:null,next_run_id:"actual-next"}}}));
 assert.match(html,/打开后续工作/);
});
