import { forwardProductEngineering } from "@/lib/product-engineering-bff";

type Context = { params: Promise<{ projectId: string; bomId: string }> };

export function POST(request: Request, context: Context) {
  return forwardProductEngineering({
    request,
    context,
    collection: "boms",
    method: "POST",
    bomItemParam: "bomId",
  });
}
