import test from "node:test";
import assert from "node:assert/strict";
import { feedbackReasons, restoreFeedback, sameFeedback } from "./run-feedback";
const id="11111111-2222-4333-8444-555555555555";
const body={idempotency_key:id,categories:["wrong_value","missing_source"] as (keyof typeof feedbackReasons)[],comment:"Specific issue",skill_load_event_id:null};
const pending={root:"v1/agent-runs",run_id:"run",owner_id:"owner",request:body};
test("六类反馈可定位问题，原请求比较遵循服务端规范化且不混用方法",()=>{
 assert.equal(Object.keys(feedbackReasons).length,6);
 assert.equal(sameFeedback(body,{...body,categories:[...body.categories].reverse(),comment:"  Specific issue  "}),true);
 assert.equal(sameFeedback(body,{...body,skill_load_event_id:id}),false);
 assert.equal(sameFeedback(body,{...body,comment:"different"}),false);
});
test("恢复只接受本人原运行和入口的完整请求，拒绝权限与版本伪造",()=>{
 assert.deepEqual(restoreFeedback(pending,"run","owner",pending.root),pending);
 for(const [value,run,owner,root] of [
   [pending,"other","owner",pending.root],[pending,"run","other",pending.root],[pending,"run","owner","v1/personal/agent-runs"],
   [{...pending,model_version:"forged"},"run","owner",pending.root],
   [{...pending,request:{...body,actor_id:"forged"}},"run","owner",pending.root],
   [{...pending,request:{...body,categories:["unknown"]}},"run","owner",pending.root],
   [{...pending,request:{...body,categories:["wrong_value","wrong_value"]}},"run","owner",pending.root],
 ] as const) assert.equal(restoreFeedback(value,run,owner,root),null);
});
