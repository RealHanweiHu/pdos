import { executionForward } from "@/lib/project-execution-bff";
export async function POST(request: Request, context: { params: Promise<{ projectId: string; changeId: string }> }) {
 const { projectId, changeId } = await context.params;
 return executionForward(request, projectId, "baseline-changes", changeId);
}
