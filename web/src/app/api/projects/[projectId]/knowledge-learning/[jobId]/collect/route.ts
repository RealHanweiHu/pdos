import { forwardLearning } from "@/lib/knowledge-learning-bff";
export async function POST(_request: Request, context: { params: Promise<{ projectId: string; jobId: string }> }) {
  const { projectId, jobId } = await context.params;
  return forwardLearning(projectId, jobId);
}
