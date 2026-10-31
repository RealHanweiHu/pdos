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
  mod.require = specifier => specifier.endsWith(".module.css") ? { __esModule: true, default: new Proxy({}, { get: (_target, key) => String(key) }) }
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier.startsWith("@/") ? load(path.join(root, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : requireLocal(specifier);
  mod._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return mod.exports;
}
const { RunProcess } = load(path.join(directory, "run-process.tsx"));
const value={run_id:"run",status:"partial",reverted:false,error_code:null,started_at:"2026-10-16T00:00:00Z",observed_at:"2026-10-16T00:01:00Z",last_recorded_at:"2026-10-16T00:01:00Z",ended_at:"2026-10-16T00:01:00Z",elapsed_seconds:60,call_counts:{total:2,completed:2,pending:0,failed:0},source_count:1,sources:[{id:"source",title:"Actual private filename <script>",bound_revision:1,current_revision:1}],next_source_cursor:null,business_receipt_count:1,receipts:[{id:"actual-receipt",operation:"evidence.claim.record",subject_id:"claim",subject_revision:1}],next_receipt_cursor:null,steps:[{id:"step",sequence:1,at:"2026-10-16T00:01:00Z",kind:"run_state",tool:null,skill:null,version:null,status:"partial"}],next_before:null};
const render=value=>renderToStaticMarkup(React.createElement(RunProcess,{value,api:()=>{throw new Error("Rendering cannot fetch or execute");},root:"v1/agent-runs"}));
test("过程保留真实部分结果与提交回执，绑定依据转义且不渲染模型原文",()=>{
 const html=render({...value,model_text:"PRIVATE REASONING",tool_arguments:"PRIVATE PARAMETERS"});
 for(const text of ["处理过程","1 分 0 秒","已提交 1 条动作","actual-receipt","仍有待完成事项","Actual private filename &lt;script&gt;","步骤返回不等于业务批准"]) assert.ok(html.includes(text),text);
 for(const secret of ["PRIVATE REASONING","PRIVATE PARAMETERS","<script>"]) assert.ok(!html.includes(secret));
});
test("空过程与旧终态如实显示，等待不会误显示已完成",()=>{
 assert.equal(render(undefined),"");
 const html=render({...value,status:"waiting_input",ended_at:null,elapsed_seconds:null,receipts:[],business_receipt_count:0,sources:[],steps:[]});
 assert.match(html,/等待你的答复或确认/); assert.match(html,/尚无已登记的处理步骤/); assert.match(html,/含等待/);
 assert.match(render({...value,status:"failed",ended_at:null,elapsed_seconds:null}),/结束时刻未记录/);
});

const { conversationProgress } = load(path.join(root, "src/lib/run-process.ts"));
const event = (sequence, kind, extra={}) => ({id:`step-${sequence}`,sequence,kind,at:value.started_at,tool:null,skill:null,version:null,status:null,...extra});
test("对话过程配对实际工具开始与返回，保留未返回步骤，不读取模型正文或参数",()=>{
 const entries=conversationProgress([
  event(1,"model_started"),event(2,"tool_started",{tool:"category.read",arguments:"PRIVATE INPUT"}),
  event(3,"tool_started",{tool:"proposal.read"}),event(4,"tool_finished",{tool:"category.read"}),
  event(5,"text_delta",{text:"PRIVATE REASONING"}),event(6,"finished",{status:"partial"}),
 ]);
 const actions=entries.flatMap(entry=>entry.kind==="tools"?entry.actions:[]);
 assert.equal(actions.length,2);assert.equal(actions[0].state,"returned");assert.equal(actions[1].state,"started");
 assert.match(JSON.stringify(entries),/仍有待完成/);
 for(const hidden of ["PRIVATE INPUT","PRIVATE REASONING","已批准"])assert.ok(!JSON.stringify(entries).includes(hidden));
});
test("对话中进行时展开、终态收起，详细步骤和提交回执不混进简短过程",()=>{
 const steps=[event(1,"accepted"),event(2,"skill_loaded",{skill:"proposal_drafting"}),event(3,"context_projected",{status:"projected"}),event(4,"model_started"),event(5,"tool_started",{tool:"proposal.create"}),event(6,"tool_finished",{tool:"proposal.create"})];
 const inline=reading=>renderToStaticMarkup(React.createElement(RunProcess,{value:{...value,steps,...reading},api:()=>{throw Error("Rendering must not execute");},root:"v1/agent-runs",presentation:"conversation"}));
 const running=inline({status:"running",ended_at:null,elapsed_seconds:null});
 assert.match(running,/<details[^>]*open=""/);assert.match(running,/正在处理/);assert.match(running,/准备立项提案/);assert.match(running,/已返回/);
 const ended=inline({status:"completed"});assert.ok(!/<details[^>]*open=/.test(ended));assert.ok(!ended.includes("actual-receipt"));assert.ok(!ended.includes("Actual private filename"));
 assert.ok(!ended.includes("反馈这次工作"));
});
test("分页边界中的工具返回仍保留，未知事件不生成推测性的过程",()=>{
 const entries=conversationProgress([event(6,"tool_finished",{tool:"proposal.read"}),event(9,"unknown_event",{tool:"SECRET TOOL",text:"SECRET"}),event(7,"model_started"),event(8,"model_started")]);
 assert.equal(entries.length,2);assert.equal(entries[0].actions[0].state,"returned");
 assert.equal(entries[1].kind,"summary");assert.ok(!JSON.stringify(entries).includes("SECRET"));
});
test("多轮处理合并连续动作，不重复堆叠相同的过渡文字",()=>{
 const entries=conversationProgress([event(1,"model_started"),event(2,"tool_started",{tool:"category.read"}),event(3,"tool_finished",{tool:"category.read"}),event(4,"model_started"),event(5,"tool_started",{tool:"proposal.read"}),event(6,"tool_finished",{tool:"proposal.read"}),event(7,"model_started")]);
 assert.equal(entries.length,2);assert.equal(entries[0].kind,"summary");
 assert.equal(entries[1].actions.length,2);assert.ok(entries[1].actions.every(action=>action.state==="returned"));
});
