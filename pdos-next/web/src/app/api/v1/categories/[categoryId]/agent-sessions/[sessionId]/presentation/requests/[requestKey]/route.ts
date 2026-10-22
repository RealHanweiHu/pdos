import type { NextRequest } from "next/server";
import { paiPresentation } from "@/lib/pai-session-presentation-proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string; sessionId: string; requestKey: string }> }) {
  const { categoryId, sessionId, requestKey } = await context.params;
  return paiPresentation(request, categoryId, sessionId, requestKey);
}
