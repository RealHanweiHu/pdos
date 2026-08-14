import { forwardProductEngineering } from "@/lib/product-engineering-bff";

type Context = { params: Promise<{ projectId: string }> };

export function GET(request: Request, context: Context) {
  return forwardProductEngineering({ request, context, collection: "boms", method: "GET" });
}

export function POST(request: Request, context: Context) {
  return forwardProductEngineering({ request, context, collection: "boms", method: "POST" });
}
