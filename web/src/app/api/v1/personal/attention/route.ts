import type { NextRequest } from "next/server";
import { personalAttentionRead } from "@/lib/server/personal-attention-proxy";

export async function GET(request: NextRequest) {
  return personalAttentionRead(request);
}
