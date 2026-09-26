import { executionForward } from "@/lib/project-execution-bff";
export async function POST(request: Request, context: { params: Promise<{ projectId: string; proposalId: string }> }) {
  const { projectId, proposalId } = await context.params;
  return executionForward(request, projectId, "cross-project-application", proposalId);
}
