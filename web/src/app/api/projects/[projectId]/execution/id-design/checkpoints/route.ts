import {executionForward} from "@/lib/project-execution-bff";
type Context={params:Promise<{projectId:string}>};
export async function GET(request:Request,context:Context){return executionForward(request,(await context.params).projectId,"id-checkpoints");}
