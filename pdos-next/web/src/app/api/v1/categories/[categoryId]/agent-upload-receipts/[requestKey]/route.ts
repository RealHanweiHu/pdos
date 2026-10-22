import type { NextRequest } from "next/server";
import { paiUploadRead } from "@/lib/pai-upload-proxy";
export async function GET(request: NextRequest, context: { params: Promise<{ categoryId: string; requestKey: string }> }) {
  const { categoryId, requestKey } = await context.params;
  return paiUploadRead(request, categoryId, requestKey);
}
