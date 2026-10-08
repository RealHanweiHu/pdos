export const WORK_MODULES = ["product", "project", "engineering", "quality", "introduction", "supply", "portfolio"] as const;

export type WorkModule = (typeof WORK_MODULES)[number];

export function isWorkModule(value: unknown): value is WorkModule {
  return typeof value === "string" && WORK_MODULES.includes(value as WorkModule);
}

export function isWorkModules(value: unknown): value is WorkModule[] {
  return Array.isArray(value) && value.every(isWorkModule);
}
