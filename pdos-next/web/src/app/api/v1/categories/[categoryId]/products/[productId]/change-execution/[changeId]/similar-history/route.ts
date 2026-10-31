import type { NextRequest } from "next/server";
import { similarHistoryProxy } from "@/lib/similar-history-proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string; productId: string; changeId: string }> }) {
  return similarHistoryProxy(request, context.params, false, "change");
}
