import type { NextRequest } from "next/server";
import { similarHistorySuggestionsProxy } from "@/lib/similar-history-proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string; productId: string }> }) {
  return similarHistorySuggestionsProxy(request, context.params);
}
