import { forwardLearning } from "@/lib/knowledge-learning-bff";
export async function GET(_request: Request, context: { params: Promise<{ projectId: string }> }) {
  return forwardLearning((await context.params).projectId);
}
