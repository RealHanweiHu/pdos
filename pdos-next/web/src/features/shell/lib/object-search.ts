export const searchKinds = { all: "全部对象", project: "项目", product: "型号", proposal: "立项提案", category: "品类" } as const;
export type SearchKind = keyof typeof searchKinds;
export type SearchItem = { kind: Exclude<SearchKind, "all">; id: string; title: string; category_id: string; category_name: string; product_id: string | null };
export type SearchPage = { query: string; kind: SearchKind; items: SearchItem[]; next_cursor: string | null; as_of: string };
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;

export function searchHref(item: SearchItem): string | null {
  if (!uuid.test(item.id) || !uuid.test(item.category_id)) return null;
  if (item.kind === "proposal") return `/categories/${item.category_id}/proposals/${item.id}`;
  if (item.kind === "project") return `?${new URLSearchParams({ area: "cockpit", category: item.category_id, project: item.id })}`;
  if (item.kind === "category" && item.id === item.category_id) return `?${new URLSearchParams({ area: "category", category: item.id })}`;
  if (item.kind === "product" && item.product_id === item.id) return `?${new URLSearchParams({ area: "category", category: item.category_id, bench: "products", view: "overview", product: item.id })}`;
  return null;
}
