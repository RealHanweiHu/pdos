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
const { FeedbackHistory, RunFeedback } = load(path.join(directory,"run-feedback.tsx"));
const record={id:"actual-feedback",sequence:12,recorded_at:"2026-10-16T00:00:00Z",recorded_by:"owner",request:{idempotency_key:"key",categories:["wrong_value","missing_source"],comment:"Specific <script>value</script> issue",skill_load_event_id:"skill"},versions:{model_version:"actual-model@1",skills:[{load_event_id:"skill",key:"public_research",version:"actual-skill@1",isolation:"main"}],model_route_digest:"digest",tool_definitions:{},prompt_prefixes:{},cancel_epoch:0}};
test("反馈历史保留实际版本和问题类别，文本转义且不冒充业务批准",()=>{
 const html=renderToStaticMarkup(React.createElement(FeedbackHistory,{items:[record]}));
 for(const value of ["actual-feedback","actual-model@1","actual-skill@1","数值错误","缺少来源","&lt;script&gt;"])assert.ok(html.includes(value),value);
 assert.ok(!html.includes("<script>"));
});
test("关闭反馈入口不读取或保存，不伪造模型版本",()=>{
 const html=renderToStaticMarkup(React.createElement(RunFeedback,{api:()=>{throw new Error("Closed feedback cannot access host");},root:"v1/agent-runs",runId:"run"}));
 assert.match(html,/反馈这次工作/);assert.ok(!html.includes("actual-model@1"));
 const unknown=renderToStaticMarkup(React.createElement(FeedbackHistory,{items:[{...record,versions:{...record.versions,model_version:null,skills:[]}}]}));
 assert.match(unknown,/本次尚无模型执行版本/);assert.match(unknown,/尚无实际加载的方法/);
});
