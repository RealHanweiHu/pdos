import { forwardNpi } from "@/lib/npi-bff";

type Context = {
  params: Promise<{ projectId: string; npiPath?: string[] }>;
};

export function GET(request: Request, context: Context) {
  return forwardNpi("GET", request, context);
}

export function POST(request: Request, context: Context) {
  return forwardNpi("POST", request, context);
}

export function PATCH(request: Request, context: Context) {
  return forwardNpi("PATCH", request, context);
}

export function PUT(request: Request, context: Context) {
  return forwardNpi("PUT", request, context);
}
