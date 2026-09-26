import { executionForward } from "@/lib/project-execution-bff";
export async function GET(request: Request, context: { params: Promise<{ projectId: string }> }) {
  const params = await context.params;
  return executionForward(request, params.projectId, "list");
}
