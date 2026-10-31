export type ContinuationSource = { artifact_id: string; expected_revision: number };
export type ContinuationRequest = { goal: string; idempotency_key: string; continue_from_run_id: string; sources?: ContinuationSource[] };
export type PendingContinuation = { root: string; owner_id: string; request: ContinuationRequest };
export type ContinuationReading = { run_id: string; owner_id: string; can_continue: boolean; existing: {run_id:string;goal:string;idempotency_key:string}|null };
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const record = (value:unknown):value is Record<string,unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const validSources = (value:unknown) => value === undefined || Array.isArray(value) && value.every(source => record(source) && Object.keys(source).length === 2 && uuid.test(String(source.artifact_id)) && typeof source.expected_revision === "number" && Number.isSafeInteger(source.expected_revision) && source.expected_revision > 0) && new Set(value.map(source => source.artifact_id)).size === value.length;
export function restoreContinuation(value:unknown,root:string,ownerId:string,runId:string):PendingContinuation|null {
  if(!record(value)||Object.keys(value).some(key=>!["root","owner_id","request"].includes(key))||value.root!==root||value.owner_id!==ownerId||!record(value.request))return null;
  const request=value.request;
  if(Object.keys(request).some(key=>!["goal","idempotency_key","continue_from_run_id","sources"].includes(key))||request.continue_from_run_id!==runId||typeof request.idempotency_key!=="string"||!uuid.test(request.idempotency_key)||typeof request.goal!=="string"||request.goal.trim().length<1||request.goal.length>8000||!validSources(request.sources))return null;
  return value as PendingContinuation;
}
export function matchesContinuation(request:ContinuationRequest,value:ContinuationReading):boolean {
  return value.run_id===request.continue_from_run_id && value.existing?.idempotency_key===request.idempotency_key && value.existing.goal===request.goal.trim();
}
