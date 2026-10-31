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

function metric(overrides={}) {
 return {version:1,window:32000,window_configured:false,reserve:6000,focus:26000,
  estimated_input_tokens:16000,admission_tokens:18400,actual_input_tokens:20000,actual_output_tokens:10,
  segments:{system:{estimated_tokens:9000,actual_tokens:null},tools:{estimated_tokens:4000,actual_tokens:null},skills:{estimated_tokens:0,actual_tokens:null},envelope:{estimated_tokens:1000,actual_tokens:null},history:{estimated_tokens:1000,actual_tokens:null},loop:{estimated_tokens:1000,actual_tokens:null}},
  estimation_error_ratio:.2,estimation_error_streak:2,calibration_factor:1.15,estimation_basis:"first_call_estimate",
  cache:{read_tokens:5000,creation_tokens:0,read_hit_ratio:.25,reporting:"positive_usage_reported",status:null,input_includes_cache:true},
  cleanup:{triggered:true,applied:true,minimum_tokens:5200,before_tokens:32000,after_tokens:26000,saved_tokens:6000,candidate_saved_tokens:6000,eligible_results:2,protected_results:4,retained_latest_results:2,replaced_results:2,cache_invalidation_from_message:2,reason:"minimum_reached"},cleanup_count:3,
  history:{carried:3,kept:2,updated:1,hidden:1,unclassified:0,truncated:1,directories:0},
  work_state:{revision:7,context_incomplete:false,item_counts:{constraints:1,exclusions:2,focus_objects:1,citations:3}},
  run_budget:{limit:100000,used:9000,held:1000,remaining:90000},context_incomplete:false,call_state:"completed",usage_status:"recorded",isolation:"main",
  warnings:["fixed_over_half_focus","cleanup_more_than_twice","persistent_estimation_error"],
  reductions_count:1,reductions:[{kind:"older_tool_result",field:"messages[2]",recoverable:true}],missing_count:0,missing:[],...overrides};
}
function metricStep(sequence=2, overrides={}) {return event(sequence,"context_observed",{context_metrics:metric(overrides)});}
test("原运行过程默认一行收起携带和省略，展开包含实际指标且不渲染未选字段",()=>{
 const html=render({...value,steps:[metricStep(2,{private_body:"PRIVATE SOURCE",charged_tokens:999999})]});
 assert.match(html,/携带历史 3 轮 · 工作状态第 7 版 · 本次新增省略 1 项/);
 assert.match(html,/<details aria-label="上下文携带与省略详情"[^>]*>/);
 assert.doesNotMatch(html,/<details aria-label="上下文携带与省略详情"[^>]*open=/);
 for(const text of ["模型窗口 W","32,000","预留 R","6,000","聚焦上限 F","26,000","本次实际输入","20,000","5,000","25%","各段计量","受保护结果","可按当前权限续读","因权限隐藏","已记账"])assert.ok(html.includes(text),text);
 for(const hidden of ["PRIVATE SOURCE","999999"])assert.ok(!html.includes(hidden),hidden);
 assert.ok(!html.includes(">0%</dd>"));
});
test("四类告警只用实际事件标记，未知用量不会显示为0或预约实测",()=>{
 const metrics=metric({actual_input_tokens:null,actual_output_tokens:null,usage_status:"unavailable",call_state:"unknown",cache:{read_tokens:0,creation_tokens:0,read_hit_ratio:null,reporting:"zero_or_unreported",status:null,input_includes_cache:true},context_incomplete:true,warnings:["fixed_over_half_focus","context_incomplete","cleanup_more_than_twice","persistent_estimation_error","PRIVATE WARNING"],missing_count:1,missing:[{field:"work_state.constraints",estimated_tokens:9000}]});
 const html=render({...value,steps:[event(2,"context_admission_observed",{context_metrics:metrics})]});
 for(const text of ["4 项告警","本次模型调用已停止","已清理超过 2 次","连续至少两次","调用实际用量尚未核实","未装入的必需内容","约束","未知","0 无法区分"])assert.ok(html.includes(text),text);
 assert.ok(!html.includes("PRIVATE WARNING"));
 assert.ok(!html.includes("999,999"));
});
test("上下文指标同样进入原对话过程，原始正文和回执不混入这个折叠层",()=>{
 const html=renderToStaticMarkup(React.createElement(RunProcess,{value:{...value,steps:[metricStep()]},api:()=>{throw Error("Rendering must not execute");},root:"v1/agent-runs",presentation:"conversation"}));
 assert.match(html,/上下文携带与省略详情/);assert.match(html,/本次新增省略 1 项/);
 assert.ok(!html.includes("actual-receipt"));assert.ok(!html.includes("Actual private filename"));
 const legacy=render({...value,steps:[event(1,"model_started")]});
 assert.ok(!legacy.includes("上下文携带与省略详情"));
});
test("后续页可展示较早调用，最近摘要按实际步骤顺序且不合计每次重复携带",()=>{
 const html=render({...value,steps:[metricStep(8,{history:{carried:2},reductions_count:0}),metricStep(3,{history:{carried:5},reductions_count:4})]});
 assert.match(html,/携带历史 2 轮.*本次新增省略 0 项/);
 assert.match(html,/较早计量 · 步骤 3/);
 assert.ok(!html.includes("携带历史 7 轮"));
});

test("主调用摘要不被较晚只读抽取的未知工作状态替代，子任务计量独立标注",()=>{
 const html=render({...value,steps:[metricStep(8,{history:{carried:3},isolation:"main"}),metricStep(9,{history:null,work_state:null,isolation:"assistant_extract"})]});
 assert.match(html,/携带历史 3 轮/);assert.match(html,/最近主调用计量 · 步骤 8/);assert.match(html,/其他计量 · 步骤 9 · 证据抽取/);
});
