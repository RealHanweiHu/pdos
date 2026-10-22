import type { NextRequest } from "next/server";
import { paiOriginalUpload } from "@/lib/pai-upload-proxy";
export async function POST(request: NextRequest, context: { params: Promise<{ categoryId: string; productId: string }> }) {
  const { categoryId, productId } = await context.params;
  return paiOriginalUpload(request, categoryId, productId);
}
