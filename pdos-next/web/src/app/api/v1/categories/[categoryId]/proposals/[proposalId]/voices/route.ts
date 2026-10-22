import type { NextRequest } from "next/server";
import { categoryResearchRead } from "@/lib/category-research-proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string; proposalId: string }> }) {
  const { categoryId, proposalId } = await context.params;
  return categoryResearchRead(request, categoryId, proposalId);
}
