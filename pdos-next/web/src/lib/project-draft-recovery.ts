import { readProfessionalBuilds, type ProfessionalApi } from "./professional-records";

type BuildLocal = { buildId: string; drafts: Record<string, unknown>; prepared: Record<string, unknown>; pending: unknown };
type Storage = Pick<globalThis.Storage, "getItem" | "setItem">;
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);

/** Migrate only verified project drafts. Original command/key/token bytes are retained;
 * this helper performs reads and local persistence, never a domain command. */
export async function restoreProjectBuildDraft<T extends BuildLocal>(storage: Storage, key: string, legacyKey: string, restore: (value: unknown) => T | null, api: ProfessionalApi, productId: string, projectId: string, active: () => boolean): Promise<T | null> {
  const scoped = storage.getItem(key);
  if (scoped !== null) return restore(JSON.parse(scoped));
  if (!projectId || legacyKey === key) return null;
  const legacy = storage.getItem(legacyKey);
  if (legacy === null) return null;
  const saved = restore(JSON.parse(legacy));
  if (!saved) return null;
  const reading = await readProfessionalBuilds(api, productId, projectId);
  if (!active()) return null;
  if (reading.incomplete || reading.unavailable > 0) throw new Error("旧草稿的项目范围尚未读全，已保留原请求。请重新读取后恢复。");
  const allowed = new Set(reading.items.map(row => row.id));
  const pending = record(saved.pending) ? saved.pending : null;
  const payload = pending && record(pending.command) && record(pending.command.payload) ? pending.command.payload : pending && record(pending.request) ? pending.request : null;
  if (saved.pending && typeof payload?.build_id !== "string") throw new Error("旧请求的轮次尚无法核对，请保留原记录并重新读取。");
  const ownedPending = payload && allowed.has(String(payload.build_id)) ? saved.pending : null;
  const next = { ...saved, buildId: ownedPending ? String(payload!.build_id) : allowed.has(saved.buildId) ? saved.buildId : "", drafts: Object.fromEntries(Object.entries(saved.drafts).filter(([id]) => allowed.has(id))), prepared: Object.fromEntries(Object.entries(saved.prepared).filter(([id]) => allowed.has(id))), pending: ownedPending } as T;
  // Save the new key first. Preserve the old key as a recovery source for other projects.
  storage.setItem(key, JSON.stringify(next));
  return next;
}
