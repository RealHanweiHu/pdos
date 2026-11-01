import type { NextRequest } from "next/server";
import { paiSessionsRead } from "@/lib/server/pai-sessions-proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await context.params;
  return paiSessionsRead(request, undefined, sessionId);
}
