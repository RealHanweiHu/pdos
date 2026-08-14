import { forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

const ROUTE_KEY = /^[A-Za-z0-9_-]{16,64}$/;
const SIGNATURE = /^[0-9a-f]{40}$/;
const TIMESTAMP = /^\d{10}(?:\d{3})?$/;
const NONCE = /^[A-Za-z0-9._~-]{1,128}$/;
const MAX_CALLBACK_BYTES = 1_500_000;

type RouteContext = { params: Promise<{ routeKey: string }> };

export async function POST(request: Request, context: RouteContext) {
  try {
    const { routeKey } = await context.params;
    if (!ROUTE_KEY.test(routeKey)) {
      return sessionError(404, "DINGTALK_CALLBACK_ROUTE_UNKNOWN", "DingTalk callback not found");
    }
    const source = new URL(request.url);
    const signature =
      source.searchParams.get("signature") ?? source.searchParams.get("msg_signature");
    const timestamp =
      source.searchParams.get("timestamp") ?? source.searchParams.get("timeStamp");
    const nonce = source.searchParams.get("nonce");
    if (
      !signature ||
      !SIGNATURE.test(signature) ||
      !timestamp ||
      !TIMESTAMP.test(timestamp) ||
      !nonce ||
      !NONCE.test(nonce)
    ) {
      return sessionError(400, "INVALID_REQUEST", "DingTalk callback parameters are required");
    }
    if (
      request.headers.get("content-type")?.split(";", 1)[0]?.trim().toLowerCase() !==
      "application/json"
    ) {
      return sessionError(400, "INVALID_REQUEST", "DingTalk callback must be JSON");
    }
    const body = await request.text();
    if (new TextEncoder().encode(body).byteLength > MAX_CALLBACK_BYTES) {
      return sessionError(413, "INVALID_REQUEST", "DingTalk callback is too large");
    }
    const query = new URLSearchParams({ signature, timestamp, nonce });
    return forwardJson(
      await pdosApiFetch(
        `/api/integrations/dingtalk/callback/${encodeURIComponent(routeKey)}?${query}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        },
      ),
    );
  } catch {
    return sessionError(503, "DINGTALK_UNAVAILABLE", "DingTalk callback unavailable");
  }
}
