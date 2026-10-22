import type { NextRequest } from "next/server";
import { paiOriginalUpload } from "@/lib/pai-upload-proxy";
export async function POST(request: NextRequest, context: { params: Promise<{ categoryId: string }> }) {
  const { categoryId } = await context.params;
  return paiOriginalUpload(request, categoryId);
}
