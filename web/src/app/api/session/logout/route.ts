import { clearSession, sessionJson } from "@/lib/pdos-api";

export async function POST() {
  await clearSession();
  return sessionJson({ authenticated: false });
}
