import type { NextRequest } from "next/server";
import { similarHistoryProxy } from "@/lib/server/similar-history-proxy";
export async function POST(request: NextRequest, context: { params: Promise<{ categoryId: string; productId: string; issueId: string }> }) {
  return similarHistoryProxy(request, context.params, true);
}
