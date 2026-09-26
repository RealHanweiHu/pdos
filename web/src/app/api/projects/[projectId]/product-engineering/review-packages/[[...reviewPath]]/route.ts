import { forwardEngineeringReview } from "@/lib/product-engineering-bff";
type Context = { params: Promise<{ projectId: string; reviewPath?: string[] }> };
export function GET(request: Request, context: Context) { return forwardEngineeringReview("GET", request, context); }
export function POST(request: Request, context: Context) { return forwardEngineeringReview("POST", request, context); }
