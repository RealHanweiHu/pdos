export type SearchPreferences = { scope: "current" | "same_category"; include_customer_private: boolean };
export const defaultSearchPreferences: SearchPreferences = { scope: "same_category", include_customer_private: false };
export function validSearchPreferences(value: unknown): value is SearchPreferences {
  return !!value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).length === 2
    && ["current", "same_category"].includes(String((value as SearchPreferences).scope))
    && typeof (value as SearchPreferences).include_customer_private === "boolean";
}
