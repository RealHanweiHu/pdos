import type { NextRequest } from "next/server";
import { personalAttentionRead } from "@/lib/personal-attention-proxy";

export async function GET(request: NextRequest) {
  return personalAttentionRead(request);
}
