import {
  InvalidRequestBodyError,
  pdosApiFetch,
  parseTokenResponse,
  persistSession,
  readBoundedJson,
  sessionError,
  sessionJson,
} from "@/lib/pdos-api";

export async function POST(request: Request) {
  try {
    const payload = await readBoundedJson(request);
    const upstream = await pdosApiFetch("/api/integrations/dingtalk/oauth/callback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!upstream.ok) {
      return sessionError(upstream.status, "DINGTALK_LOGIN_REJECTED", "DingTalk login rejected");
    }
    const body: unknown = await upstream.json();
    const token = parseTokenResponse(body);
    await persistSession(token);
    const returnPath =
      body &&
      typeof body === "object" &&
      "return_path" in body &&
      typeof body.return_path === "string" &&
      body.return_path.startsWith("/") &&
      !body.return_path.startsWith("//") &&
      !body.return_path.includes("\\")
        ? body.return_path
        : "/";
    return sessionJson({
      authenticated: true,
      expires_in: token.expires_in,
      return_path: returnPath,
    });
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "A bounded JSON object is required");
    }
    return sessionError(503, "DINGTALK_UNAVAILABLE", "DingTalk login unavailable");
  }
}
