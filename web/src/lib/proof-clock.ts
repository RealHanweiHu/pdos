export function proofClockCurrent(tier: string, expires: unknown, now = Date.now()): boolean {
  if (!Number.isFinite(now)) return false;
  if (expires === null) return tier === "T2";
  return typeof expires === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(expires)
    && Number.isFinite(Date.parse(expires)) && Date.parse(expires) > now;
}
