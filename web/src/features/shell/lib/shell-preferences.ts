import { parsePersonalAttention, type AttentionQueue } from "@/features/my-work/lib/personal-attention";
import type { GlobalArea } from "@/lib/global-navigation";

/** The two interface settings the shell uses (D40); everything else stays in settings. */
export type ShellPreferences = { default_home: "work" | "inbox" | "projects"; pending_reminders: boolean };
export const defaultShellPreferences: ShellPreferences = { default_home: "work", pending_reminders: true };
type Api = <T>(path: string) => Promise<T>;

const homes = new Set(["work", "inbox", "projects"]);
/** A missing or unexpected value falls back to the app default instead of failing the shell. */
export function shellPreferences(value: unknown): ShellPreferences {
  const preferences = value && typeof value === "object" ? (value as { preferences?: Record<string, unknown> }).preferences ?? value : null;
  const record = preferences && typeof preferences === "object" ? preferences as Record<string, unknown> : {};
  return {
    default_home: typeof record.default_home === "string" && homes.has(record.default_home) ? record.default_home as ShellPreferences["default_home"] : "work",
    pending_reminders: typeof record.pending_reminders === "boolean" ? record.pending_reminders : true,
  };
}

/** Only a bare entry (no page, category or project named) opens the chosen home. */
export function defaultHomeArea(search: string, preferences: ShellPreferences): GlobalArea | null {
  const params = new URLSearchParams(search);
  if (["area", "category", "project", "bench"].some(key => params.has(key))) return null;
  return preferences.default_home === "work" ? null : preferences.default_home;
}

/** Items that need me: 要我决定 + 接收 + 验证. Waiting on others is not counted. */
export const reminderQueues: AttentionQueue[] = ["decide", "receive", "verify"];
export async function readPendingCount(api: Api, principalId: string): Promise<number> {
  const pages = await Promise.all(reminderQueues.map(queue =>
    api<unknown>(`v1/personal/attention?${new URLSearchParams({ queue, page_size: "1" })}`).then(value => parsePersonalAttention(value, principalId, queue))));
  return pages.reduce((total, page) => total + page.total_records, 0);
}

export const countText = (count: number) => count > 99 ? "99+" : String(count);
