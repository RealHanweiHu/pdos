import test from "node:test";
import assert from "node:assert/strict";
import {matchesContinuation,restoreContinuation} from "./run-continuation";
const parent="11111111-2222-4333-8444-555555555555",key="66666666-7777-4888-8999-aaaaaaaaaaaa";
const pending={root:"v1/agent-runs",owner_id:"owner",request:{goal:"继续原工作",idempotency_key:key,continue_from_run_id:parent}};
test("续接原请求只在实际本人、原运行和入口恢复，拒绝增加权限字段",()=>{
 assert.deepEqual(restoreContinuation(pending,pending.root,"owner",parent),pending);
 for(const value of [{...pending,owner_id:"other"},{...pending,root:"v1/personal/agent-runs"},{...pending,request:{...pending.request,continue_from_run_id:key}},{...pending,request:{...pending.request,product_id:key}},{...pending,request:{...pending.request,goal:" "}},{...pending,request:{...pending.request,idempotency_key:"not-a-key"}}])assert.equal(restoreContinuation(value,pending.root,"owner",parent),null);
});
test("后续恢复核对原编号和目标，不将其他后续记录冒充原受理",()=>{
 const reading={run_id:parent,owner_id:"owner",can_continue:false,existing:{run_id:key,goal:"继续原工作",idempotency_key:key}};
 assert.equal(matchesContinuation(pending.request,reading),true);
 assert.equal(matchesContinuation({...pending.request,goal:"不同目标"},reading),false);
 assert.equal(matchesContinuation({...pending.request,idempotency_key:parent},reading),false);
 assert.equal(matchesContinuation(pending.request,{...reading,run_id:key}),false);
});
