import type { NextRequest } from "next/server";
import { categoryResearchRead } from "@/lib/category-research-proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string }> }) {
  return categoryResearchRead(request, (await context.params).categoryId);
}
