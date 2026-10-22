import type { NextRequest } from "next/server";
import { paiPresentation } from "@/lib/pai-session-presentation-proxy";

export async function POST(request: NextRequest, context: { params: Promise<{ categoryId: string; sessionId: string }> }) {
  const { categoryId, sessionId } = await context.params;
  return paiPresentation(request, categoryId, sessionId);
}
