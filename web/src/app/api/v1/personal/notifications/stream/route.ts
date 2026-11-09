import type { NextRequest } from "next/server";
import { notificationStream } from "@/lib/server/notification-stream-proxy";

export async function GET(request: NextRequest) {
  return notificationStream(request);
}
