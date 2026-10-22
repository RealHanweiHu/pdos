import type { NextRequest } from "next/server";
import { paiPresentation } from "@/lib/pai-session-presentation-proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ sessionId: string; requestKey: string }> }) {
  const { sessionId, requestKey } = await context.params;
  return paiPresentation(request, undefined, sessionId, requestKey);
}
