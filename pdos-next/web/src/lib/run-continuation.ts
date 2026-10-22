export type ContinuationRequest = { goal: string; idempotency_key: string; continue_from_run_id: string };
export type PendingContinuation = { root: string; owner_id: string; request: ContinuationRequest };
export type ContinuationReading = { run_id: string; owner_id: string; can_continue: boolean; existing: {run_id:string;goal:string;idempotency_key:string}|null };
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const record = (value:unknown):value is Record<string,unknown> => !!value && typeof value === "object" && !Array.isArray(value);
export function restoreContinuation(value:unknown,root:string,ownerId:string,runId:string):PendingContinuation|null {
  if(!record(value)||Object.keys(value).some(key=>!["root","owner_id","request"].includes(key))||value.root!==root||value.owner_id!==ownerId||!record(value.request))return null;
  const request=value.request;
  if(Object.keys(request).some(key=>!["goal","idempotency_key","continue_from_run_id"].includes(key))||request.continue_from_run_id!==runId||typeof request.idempotency_key!=="string"||!uuid.test(request.idempotency_key)||typeof request.goal!=="string"||request.goal.trim().length<3||request.goal.length>8000)return null;
  return value as PendingContinuation;
}
export function matchesContinuation(request:ContinuationRequest,value:ContinuationReading):boolean {
  return value.run_id===request.continue_from_run_id && value.existing?.idempotency_key===request.idempotency_key && value.existing.goal===request.goal.trim();
}
