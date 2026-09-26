import { forwardKnowledgeFeedback } from "@/lib/knowledge-push-bff";

export async function POST(request: Request, context: { params: Promise<{ pushId: string }> }) {
  return forwardKnowledgeFeedback(request, (await context.params).pushId);
}
