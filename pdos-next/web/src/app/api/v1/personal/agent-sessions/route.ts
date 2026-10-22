import type { NextRequest } from "next/server";
import { paiSessionsRead } from "@/lib/pai-sessions-proxy";

export async function GET(request: NextRequest) {
  return paiSessionsRead(request);
}
