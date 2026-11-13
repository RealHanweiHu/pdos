import { parsePersonalAttention, type AttentionQueue } from "@/features/my-work/lib/personal-attention";
import type { GlobalArea } from "@/lib/global-navigation";
import { parseRunDecisions, runDecisionsPath } from "@/features/my-work/lib/run-decisions-read";

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

/** A bare entry names no page, category or project; only it opens the chosen home. */
export function bareEntry(search: string): boolean {
  const params = new URLSearchParams(search);
  return !["area", "category", "project", "bench"].some(key => params.has(key));
}
export function defaultHomeArea(search: string, preferences: ShellPreferences): GlobalArea | null {
  if (!bareEntry(search)) return null;
  return preferences.default_home === "work" ? null : preferences.default_home;
}
/** D341: how long a bare entry waits for the saved home before showing the app default. */
export const homeWaitMs = 1500;

/**
 * Items that need me (D341): 要我决定 (named reviews and, per D78, each 小Pai run waiting on
 * my confirmation or answer, counted once per run) + 要我接收 + 要我验证. Waiting on
 * others and my own in-progress tasks are not reminders.
 */
export const reminderQueues: AttentionQueue[] = ["decide", "receive", "verify"];
export async function readPendingCount(api: Api, principalId: string): Promise<number> {
  const [pages, runs] = await Promise.all([
    Promise.all(reminderQueues.map(queue =>
      api<unknown>(`v1/personal/attention?${new URLSearchParams({ queue, page_size: "1" })}`).then(value => parsePersonalAttention(value, principalId, queue)))),
    api<unknown>(runDecisionsPath).then(value => parseRunDecisions(value, principalId)),
  ]);
  return pages.reduce((total, page) => total + page.total_records, runs.total_runs);
}

export const countText = (count: number) => count > 99 ? "99+" : String(count);
