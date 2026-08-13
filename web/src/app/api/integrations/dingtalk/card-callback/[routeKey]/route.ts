import { forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

const ROUTE_KEY = /^[A-Za-z0-9_-]{16,64}$/;
const TIMESTAMP = /^\d{10}(?:\d{3})?$/;
const SIGNATURE = /^[A-Za-z0-9+/]{43}=$/;
// The fixed `content` field may itself be 16 KiB; leave bounded room for the JSON envelope.
const MAX_CARD_CALLBACK_BYTES = 65_536;

type RouteContext = { params: Promise<{ routeKey: string }> };

export async function POST(request: Request, context: RouteContext) {
  try {
    const { routeKey } = await context.params;
    if (!ROUTE_KEY.test(routeKey)) {
      return sessionError(404, "DINGTALK_CALLBACK_ROUTE_UNKNOWN", "DingTalk callback not found");
    }
    const timestamp = request.headers.get("x-ddpaas-signature-timestamp");
    const signature = request.headers.get("x-ddpaas-signature");
    if (!timestamp || !TIMESTAMP.test(timestamp) || !signature || !SIGNATURE.test(signature)) {
      return sessionError(400, "INVALID_REQUEST", "DingTalk callback headers are required");
    }
    if (
      request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase() !==
      "application/json"
    ) {
      return sessionError(400, "INVALID_REQUEST", "DingTalk callback must be JSON");
    }
    const body = await request.text();
    if (new TextEncoder().encode(body).byteLength > MAX_CARD_CALLBACK_BYTES) {
      return sessionError(413, "INVALID_REQUEST", "DingTalk callback is too large");
    }
    return forwardJson(
      await pdosApiFetch(
        `/api/integrations/dingtalk/card-callback/${encodeURIComponent(routeKey)}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-ddpaas-signature-timestamp": timestamp,
            "x-ddpaas-signature": signature,
          },
          body,
        },
      ),
    );
  } catch {
    return sessionError(503, "DINGTALK_UNAVAILABLE", "DingTalk callback unavailable");
  }
}
