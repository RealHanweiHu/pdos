import { forwardEngage } from "@/lib/knowledge-push-bff";

type Context = { params: Promise<{ pushId: string }> };

export async function POST(_request: Request, context: Context) {
  const { pushId } = await context.params;
  return forwardEngage(pushId);
}
