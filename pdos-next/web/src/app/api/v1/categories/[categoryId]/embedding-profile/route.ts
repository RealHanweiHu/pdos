import type { NextRequest } from "next/server";
import { embeddingSettingsRead } from "@/lib/embedding-settings-proxy";

export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string }> }) {
  const { categoryId } = await context.params;
  return embeddingSettingsRead(request, categoryId);
}
