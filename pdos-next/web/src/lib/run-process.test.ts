import test from "node:test";
import assert from "node:assert/strict";
import { actionLabel, contextIssueLabel, mergeProcessSteps, processAge, processStepLabel } from "./run-process";
import type { ProcessStep, RunProcessData } from "./run-process";

const step = (sequence:number, kind="model_started"):ProcessStep => ({ id:`event-${sequence}`, sequence, kind, at:"2026-10-16T00:01:00Z", tool:null, skill:null, version:null, status:null });
const reading = { status:"running", started_at:"2026-10-16T00:00:00Z", observed_at:"2026-10-16T00:01:00Z", elapsed_seconds:null } as RunProcessData;
test("资料合同步骤区分已投影和拒绝，省略原因不用原字段值",()=>{
  assert.match(processStepLabel({...step(1,"context_projected"),status:"projected",context_omitted:[{field:"/proposal/extra",reason:"outside_skill_context_schema"}]}),/省略 1 个字段/);
  assert.match(processStepLabel({...step(1,"context_projected"),status:"rejected"}),/不匹配/);
  assert.equal(contextIssueLabel({field:"/proposal/extra",reason:"outside_skill_context_schema"}),"当前提案：当前方法未声明使用这一字段，未提供给模型");
  assert.match(contextIssueLabel({field:"/sources",reason:"context_required"}),/必要字段/);
});
test("终态使用真实结束时间，运行与等待按服务器观察时刻计龄，旧记录不补造结束",()=>{
  assert.equal(processAge(reading,5),"1 分 5 秒");
  assert.equal(processAge({...reading,status:"waiting_input"},5),"1 分 5 秒");
  assert.equal(processAge({...reading,status:"cancelled",elapsed_seconds:65},9000),"1 分 5 秒");
  assert.equal(processAge({...reading,status:"failed"},9000),"结束时刻未记录");
  assert.equal(processAge({...reading,observed_at:"bad"}),"时间记录暂不可核对");
});
test("公开步骤标签解释实际动作，不把处理返回当作业务批准",()=>{
  assert.match(actionLabel("mcp.read"),/已授权/);
  assert.match(processStepLabel({...step(1,"tool_finished"),tool:"proposal.create"}),/本步处理已返回/);
  assert.match(processStepLabel({...step(1,"run_state"),status:"partial"}),/待完成/);
  assert.match(processStepLabel({...step(1,"skill_loaded"),skill:"public_research",version:"1"}),/公开研究/);
  assert.equal(processStepLabel({...step(1,"text_delta"),tool:"private reasoning"}),"已登记处理步骤");
});
test("过程分页保留已读步骤并以最新读取覆盖同一序号，不重排或重复",()=>{
  const latest={...step(3),kind:"tool_finished"};
  const result=mergeProcessSteps([step(1),step(2),step(3)],[latest,step(4)]);
  assert.deepEqual(result.map(row=>row.sequence),[1,2,3,4]);
  assert.equal(result[2].kind,"tool_finished");
});
