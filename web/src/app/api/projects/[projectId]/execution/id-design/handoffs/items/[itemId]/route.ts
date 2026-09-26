import { executionForward } from "@/lib/project-execution-bff";
type Context = { params: Promise<{ projectId: string; itemId: string }> };
export async function POST(request: Request, context: Context) { const p=await context.params; return executionForward(request, p.projectId, "id-handoff-response", p.itemId); }
