import type { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/request-origin";
import { validPreferenceSave } from "@/lib/personal-preferences";
import { preferenceError, preferenceProxy } from "@/lib/personal-preferences-proxy";

export async function GET(request: NextRequest) {
  if (request.nextUrl.searchParams.size) return preferenceError("个人偏好不接受其他身份或范围。", 422);
  return preferenceProxy("");
}

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) return preferenceError("请从当前站点保存设置。", 403, "FORBIDDEN_SCOPE");
  if (request.nextUrl.searchParams.size) return preferenceError("个人偏好不接受其他身份或范围。", 422);
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) return preferenceError("请提交 JSON 设置。", 422);
  let value: unknown;
  try {
    const text = await request.text();
    if (text.length > 16384) return preferenceError("设置内容过长。", 422);
    value = JSON.parse(text);
  } catch { return preferenceError("设置内容无效。", 422); }
  if (!validPreferenceSave(value)) return preferenceError("请只保存有效的本人偏好。", 422);
  return preferenceProxy("", value);
}
