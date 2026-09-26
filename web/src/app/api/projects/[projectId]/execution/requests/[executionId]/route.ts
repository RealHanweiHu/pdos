import { executionForward } from "@/lib/project-execution-bff";
export async function POST(request: Request, context: { params: Promise<{ projectId: string; executionId: string }> }) {
  const params = await context.params;
  return executionForward(request, params.projectId, "requests", params.executionId);
}
