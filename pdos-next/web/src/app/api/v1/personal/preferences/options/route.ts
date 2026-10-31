import type { NextRequest } from "next/server";
import { preferenceOptionsQuery } from "@/lib/personal-preferences";
import { preferenceError, preferenceProxy } from "@/lib/personal-preferences-proxy";

export async function GET(request: NextRequest) {
  const query = preferenceOptionsQuery(request.nextUrl.searchParams);
  if (!query) return preferenceError("请提供有效的常用范围查找条件。", 422);
  return preferenceProxy(`/options?${query}`);
}
