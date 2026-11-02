import type { NextRequest } from "next/server";
import { paiConversationsRead } from "@/lib/server/pai-session-presentation-proxy";

export async function GET(request: NextRequest) {
  return paiConversationsRead(request);
}
