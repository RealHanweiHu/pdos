import { executionForward } from "@/lib/project-execution-bff";
type Context = { params: Promise<{ projectId: string; revisionId: string }> };
export async function GET(request: Request, context: Context) { const p = await context.params; return executionForward(request,p.projectId,"id-responsibility",p.revisionId); }
export async function POST(request: Request, context: Context) { const p = await context.params; return executionForward(request,p.projectId,"id-responsibility",p.revisionId); }
