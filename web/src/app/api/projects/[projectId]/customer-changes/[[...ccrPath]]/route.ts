import { forwardCustomerChanges } from "@/lib/customer-changes-bff";

type Context = {
  params: Promise<{ projectId: string; ccrPath?: string[] }>;
};

export function GET(request: Request, context: Context) {
  return forwardCustomerChanges("GET", request, context);
}

export function POST(request: Request, context: Context) {
  return forwardCustomerChanges("POST", request, context);
}
