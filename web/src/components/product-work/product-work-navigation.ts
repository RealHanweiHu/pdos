export const productViews = [
  ["overview", "总览"], ["research", "研究"], ["competitors", "竞品"],
  ["segments", "细分"], ["opportunities", "机会·策略"],
  ["definitions", "PRD·Spec"], ["experiments", "验证"],
] as const;

export function productView(tab: string) {
  if (tab === "strategies") return "opportunities";
  if (tab === "exports") return "definitions";
  return tab;
}

export function productWorkHref(space: string, tab?: string, line?: string | null, anchor?: string) {
  const params = new URLSearchParams({ space });
  if (tab) params.set("tab", tab);
  if (line !== undefined && line !== null && line !== "all") params.set("line", line);
  return `/product-work?${params}${anchor ? `#${anchor}` : ""}`;
}

export function navigateProductWork(change: { space?: string; tab?: string | null; line?: string | null }) {
  const params = change.space !== undefined ? new URLSearchParams() : new URLSearchParams(window.location.search);
  if (change.space !== undefined) {
    if (change.space) params.set("space", change.space);
  }
  if (change.tab !== undefined) {
    if (change.tab === null) params.delete("tab"); else params.set("tab", change.tab);
  }
  if (change.line !== undefined) {
    if (change.line === null || change.line === "all") params.delete("line"); else params.set("line", change.line);
  }
  for (const key of ["roadmap_product", "record_id", "run", "responsibility_kind", "responsibility_id", "history"]) params.delete(key);
  const href = `/product-work${params.size ? `?${params}` : ""}`;
  if (href !== `${window.location.pathname}${window.location.search}${window.location.hash}`) window.history.pushState(null, "", href);
}
