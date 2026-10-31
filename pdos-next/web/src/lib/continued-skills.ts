import type { RequestedSkill } from "./run-start-intent";

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);

export function validSkillSelections(value: unknown, limit = 8): value is RequestedSkill[] {
  return Array.isArray(value) && value.length <= limit && value.every(skill => record(skill)
    && Object.keys(skill).length === 3 && Object.keys(skill).every(key => ["key", "version", "digest"].includes(key))
    && typeof skill.key === "string" && skill.key.length > 0 && skill.key.length <= 160
    && typeof skill.version === "string" && skill.version.length > 0 && skill.version.length <= 160
    && typeof skill.digest === "string" && /^[a-f0-9]{64}$/.test(skill.digest))
    && new Set(value.map(skill => skill.key)).size === value.length;
}

export function validContinuedSkillExclusions(value: unknown): value is string[] {
  return Array.isArray(value) && value.length <= 2
    && value.every(key => typeof key === "string" && key.length > 0 && key.length <= 160)
    && new Set(value).size === value.length;
}

export function toggleContinuedSkill(continued: RequestedSkill[], excluded: string[], key: string): string[] {
  if (!continued.some(skill => skill.key === key)) return excluded;
  const next = new Set(excluded);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return continued.filter(skill => next.has(skill.key)).map(skill => skill.key);
}
