import type { NextRequest } from "next/server";
import { paiPresentation } from "@/lib/pai-session-presentation-proxy";

export async function POST(request: NextRequest, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  return paiPresentation(request, undefined, sessionId);
}
