import type { NextRequest } from "next/server";
import { paiSourcesRead } from "@/lib/pai-sources-proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string; runId: string }> }) {
  const { categoryId, runId } = await context.params;
  return paiSourcesRead(request, categoryId, runId);
}
