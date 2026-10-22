import type { NextRequest } from "next/server";
import { paiConversationsRead } from "@/lib/pai-session-presentation-proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string }> }) {
  const { categoryId } = await context.params;
  return paiConversationsRead(request, categoryId);
}
