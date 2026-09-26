import { forwardPushMetrics } from "@/lib/knowledge-push-bff";

export function GET() {
  return forwardPushMetrics();
}
