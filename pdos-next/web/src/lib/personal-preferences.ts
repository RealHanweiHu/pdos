export type PersonalPreferences = {
  answer_language: "auto" | "zh-CN" | "zh-TW" | "en" | "ja";
  response_detail: "brief" | "balanced" | "detailed";
  role: "product" | "engineering" | "quality" | "manufacturing" | "supply" | "management" | "other" | null;
  department: string | null;
  favorite_category_ids: string[];
  favorite_project_ids: string[];
};
export type PreferenceCandidate = { kind: "category" | "project"; id: string; label: string; category_id: string; product_id: string | null; href: string };
export type PreferenceView = { revision: number; preferences: PersonalPreferences; navigation_candidates: PreferenceCandidate[]; role_defaults: { welcome_examples: string[]; summary_sections: string[] }; updated_at: string | null };
export type PreferenceOptions = { items: PreferenceCandidate[]; next_cursor: string | null };
export const newPersonalPreferences = (): PersonalPreferences => ({ answer_language: "auto", response_detail: "balanced", role: null, department: null, favorite_category_ids: [], favorite_project_ids: [] });
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
export function validPreferenceSave(value: unknown): boolean {
  if (!record(value) || Object.keys(value).length !== 2 || !Object.keys(value).every(key => ["expected_revision", "preferences"].includes(key)) || typeof value.expected_revision !== "number" || !Number.isSafeInteger(value.expected_revision) || value.expected_revision < 0 || value.expected_revision > 2147483646 || !record(value.preferences)) return false;
  const p = value.preferences;
  return Object.keys(p).length === 6 && Object.keys(p).every(key => Object.keys(newPersonalPreferences()).includes(key))
    && typeof p.answer_language === "string" && ["auto", "zh-CN", "zh-TW", "en", "ja"].includes(p.answer_language)
    && typeof p.response_detail === "string" && ["brief", "balanced", "detailed"].includes(p.response_detail)
    && (p.role === null || typeof p.role === "string" && ["product", "engineering", "quality", "manufacturing", "supply", "management", "other"].includes(p.role))
    && (p.department === null || typeof p.department === "string" && [...p.department].length <= 80 && !/[\u0000-\u001f]/.test(p.department))
    && [p.favorite_category_ids, p.favorite_project_ids].every(ids => Array.isArray(ids) && ids.length <= 10 && ids.every(id => typeof id === "string" && uuid.test(id)) && new Set(ids.map(id => id.toLowerCase())).size === ids.length);
}

export function preferenceOptionsQuery(params: URLSearchParams): URLSearchParams | null {
  const query = new URLSearchParams();
  for (const [key, value] of params) {
    const valid = key === "kind" ? ["category", "project"].includes(value)
      : key === "query" ? [...value].length <= 100
      : key === "cursor" ? uuid.test(value)
      : key === "page_size" && /^[1-9]\d*$/.test(value) && Number(value) <= 100;
    if (!valid || query.has(key)) return null;
    query.set(key, value);
  }
  return query.has("kind") ? query : null;
}
