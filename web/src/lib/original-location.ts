export type LocatedSource = { locator_map?: { derived_line_start: number; derived_line_end: number; location: { kind: string; line?: number; page?: number; sheet?: string; cell?: string } }[] };

export function originalLocation(source: LocatedSource | undefined, line: number): string {
  const item = source?.locator_map?.find((entry) => entry.derived_line_start <= line && entry.derived_line_end >= line)?.location;
  if (!item) return "";
  if (item.kind === "page") return `原件第 ${item.page} 页`;
  if (item.kind === "cell") return `${item.sheet} · ${item.cell}`;
  return `原件第 ${item.line} 行`;
}
