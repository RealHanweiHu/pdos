import { executionForward } from "@/lib/project-execution-bff";
export async function POST(request: Request, context: { params: Promise<{ projectId: string; feedbackId: string }> }) {
  const params = await context.params;
  return executionForward(request, params.projectId, "id-design-decision", params.feedbackId);
}
