import type { NextRequest } from "next/server";
import { paiUploadRead } from "@/lib/server/pai-upload-proxy";
export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string }> }) {
  const { categoryId } = await context.params;
  return paiUploadRead(request, categoryId);
}
