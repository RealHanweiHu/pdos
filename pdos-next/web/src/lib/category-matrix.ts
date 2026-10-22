import type { ProposalViewSource } from "@/components/preproject/proposal-view-contracts";

export type MatrixSource = ProposalViewSource;
export type MatrixSubject = { type: "product" | "competitor"; id: string; label: string; revision: number; origin?: string };
export type MatrixBasis = { currency: string | null; as_of: string | null; basis: string | null; includes_tax: boolean | null; includes_shipping: boolean | null; region: string | null; channel: string | null };
export type MatrixPrice = Record<string, unknown> & { amount?: string | null; source_refs?: MatrixSource[] };
export type MatrixSegment = { lineage_id: string; version: number; entry_id: string | null; label: string | null; status: string | null; source_refs: MatrixSource[]; reasons: string[] };
export type MatrixPlacement = { subject: MatrixSubject; price: MatrixPrice; source_refs: MatrixSource[] };
export type MatrixBand = { id: string; lower: string | null; upper: string | null; lower_inclusive: boolean; upper_inclusive: boolean };
export type MatrixCell = { band_id: string; status: "observed" | "no_readable_observations"; products: MatrixPlacement[]; competitors: MatrixPlacement[]; counts: { products: number; competitors: number } };
export type CategoryMatrixResponse = {
  version: "category-matrix/v1"; category_id: string; as_of: string | null;
  display: { breaks: string[]; bands: MatrixBand[]; semantics: "read_only_distribution" };
  groups: { id: string; basis: MatrixBasis; rows: { segment: MatrixSegment; cells: MatrixCell[] }[] }[];
  unplaced: (MatrixPlacement & { fixed_segment: MatrixSegment | null; reasons: string[] })[];
  coverage: { visible_products: number; visible_competitors: number; placed_subjects: number; unplaced_subjects: number; partially_placed_subjects: number; placements: number; price_observations: number; reason_counts: Record<string, number> };
  limitations: string[];
};

/** Display inputs stay exact decimal strings; they never update a business price. */
function decimal(value: string): string | null {
  if (!/^\+?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value)) return null;
  const [integer, fraction = ""] = value.replace(/^\+/, "").split(".");
  const whole = integer.replace(/^0+/, "") || "0", part = fraction.replace(/0+$/, "");
  return part ? `${whole}.${part}` : whole;
}
function compare(left: string, right: string) {
  const [a, af = ""] = left.split("."), [b, bf = ""] = right.split(".");
  return a.length !== b.length ? a.length - b.length : a !== b ? a > b ? 1 : -1 : af.padEnd(Math.max(af.length, bf.length), "0").localeCompare(bf.padEnd(Math.max(af.length, bf.length), "0"));
}
export function matrixBreaks(input: string): string[] {
  const parts = input.trim().split(/[,，\s]+/).filter(Boolean), values = parts.map(value => decimal(value));
  if (!parts.length || parts.length > 10 || values.some(value => value === null || value === "0")) throw new Error("填写 1–10 个严格递增的正十进制分界，以逗号分隔。");
  const result = values as string[];
  if (result.some((value, index) => index > 0 && compare(result[index - 1], value) >= 0)) throw new Error("价格分界须严格递增，不能重复。");
  return result;
}
export function categoryMatrixPath(categoryId: string, breaks: readonly string[]) {
  const query = new URLSearchParams(); breaks.forEach(value => query.append("price_breaks", value));
  return `v1/categories/${encodeURIComponent(categoryId)}/category-matrix?${query}`;
}

const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === "string");
const nullableString = (value: unknown) => value === null || typeof value === "string";
const count = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const sources = (value: unknown) => Array.isArray(value) && value.every(object);
const subject = (value: unknown) => object(value) && ["product", "competitor"].includes(String(value.type)) && typeof value.id === "string" && typeof value.label === "string" && count(value.revision);
const price = (value: unknown) => object(value) && (value.amount === undefined || nullableString(value.amount));
const segment = (value: unknown) => object(value) && typeof value.lineage_id === "string" && count(value.version) && nullableString(value.entry_id) && nullableString(value.label) && nullableString(value.status) && sources(value.source_refs) && strings(value.reasons);
const placement = (value: unknown) => object(value) && subject(value.subject) && price(value.price) && sources(value.source_refs);
const basis = (value: unknown) => object(value) && ["currency", "as_of", "basis", "region", "channel"].every(key => nullableString(value[key])) && ["includes_tax", "includes_shipping"].every(key => value[key] === null || typeof value[key] === "boolean");

/** Check the read envelope and scope, without deriving placement or coverage facts. */
export function isCategoryMatrixResponse(value: unknown, categoryId: string, requestedBreaks: readonly string[]): value is CategoryMatrixResponse {
  if (!object(value) || value.version !== "category-matrix/v1" || value.category_id !== categoryId || !nullableString(value.as_of) || !object(value.display)
    || value.display.semantics !== "read_only_distribution" || !strings(value.display.breaks) || value.display.breaks.length !== requestedBreaks.length
    || !value.display.breaks.every((entry, index) => decimal(entry) === decimal(requestedBreaks[index])) || !Array.isArray(value.display.bands)) return false;
  const bands = value.display.bands;
  if (bands.length !== requestedBreaks.length + 1 || !bands.every(band => object(band) && typeof band.id === "string" && nullableString(band.lower) && nullableString(band.upper) && typeof band.lower_inclusive === "boolean" && band.upper_inclusive === false)) return false;
  const ids = new Set(bands.map(band => (band as Record<string, unknown>).id));
  if (ids.size !== bands.length || !Array.isArray(value.groups) || !value.groups.every(group =>
    object(group) && typeof group.id === "string" && basis(group.basis) && Array.isArray(group.rows) && group.rows.every(row =>
      object(row) && segment(row.segment) && Array.isArray(row.cells) && row.cells.length === bands.length
      && new Set(row.cells.map(cell => object(cell) ? cell.band_id : null)).size === bands.length
      && row.cells.every(cell => object(cell) && ids.has(cell.band_id)
        && ["observed", "no_readable_observations"].includes(String(cell.status))
        && Array.isArray(cell.products) && cell.products.every(item => placement(item) && item.subject.type === "product")
        && Array.isArray(cell.competitors) && cell.competitors.every(item => placement(item) && item.subject.type === "competitor")
        && object(cell.counts) && count(cell.counts.products) && count(cell.counts.competitors))))) return false;
  return Array.isArray(value.unplaced) && value.unplaced.every(item => placement(item) && (item.fixed_segment === null || segment(item.fixed_segment)) && strings(item.reasons))
    && object(value.coverage) && ["visible_products", "visible_competitors", "placed_subjects", "unplaced_subjects", "partially_placed_subjects", "placements", "price_observations"].every(key => count(value.coverage && (value.coverage as Record<string, unknown>)[key]))
    && object(value.coverage.reason_counts) && Object.values(value.coverage.reason_counts).every(count) && strings(value.limitations);
}
