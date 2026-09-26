import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";
type Context = { params: Promise<{projectId:string;kind:string;policyId:string}> };
export async function GET(request:Request, context:Context) {
  const {projectId,kind,policyId}=await context.params;
  const before=new URL(request.url).searchParams.get("before_version");
  if(![projectId,policyId].every(id=>/^[0-9a-f-]{36}$/i.test(id)) || !["execution","baseline","commitment"].includes(kind) || (before!==null&&!/^[1-9][0-9]{0,8}$/.test(before))) return sessionError(400,"INVALID_REQUEST","Invalid policy reference");
  const token=await currentSessionToken();if(!token)return sessionError(401,"INVALID_ACCESS_TOKEN","Authentication required");
  try{return forwardJson(await pdosApiFetch(`/api/projects/${projectId}/execution/approval-responsibilities/${kind}/${policyId}${before ? `?before_version=${before}` : ""}`,{headers:{Authorization:`Bearer ${token}`}}));}
  catch{return sessionError(503,"POLICY_UNAVAILABLE","批准政策暂不可用");}
}
