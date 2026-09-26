import { executionForward } from "@/lib/project-execution-bff";
export async function POST(request: Request, context: { params: Promise<{ projectId: string; revisionId: string }> }) {
  const params = await context.params;
  return executionForward(request, params.projectId, "id-design-feedback", params.revisionId);
}
