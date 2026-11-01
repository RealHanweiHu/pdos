type Side = { citation_id: string; quote: string; value_kind: string; locator: Record<string, unknown> };
type Difference = { change_id: string; kind: string; aligned: boolean; label: string; old: Side | null; new: Side | null; impact: { citation_id: string; quote: string } | null; questions: string[] };
type Gap = { reason: string; citation_id?: string; sheet?: string; count?: number };
type Comparison = { rows: Difference[]; complete: boolean; citation_ids?: string[]; unmatched?: Gap[]; stats: { changes: number; unmatched_sections: number; unaligned_changes: number }; alignment_basis: { sheet: string; key_header: string }[] };
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = /^[a-f0-9-]{36}$/i;
const hash = /^[a-f0-9]{64}$/;
const integer = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
function side(value: unknown): value is Side | null {
  return value === null || object(value) && typeof value.citation_id === "string" && uuid.test(value.citation_id) && typeof value.quote === "string" && value.quote.length <= 1000 && typeof value.value_kind === "string" && object(value.locator);
}
function comparison(value: unknown): Comparison | null {
  if (!object(value) || value.version !== 1 || value.format !== "comparison" || typeof value.complete !== "boolean" || !object(value.stats) || !integer(value.stats.changes) || !integer(value.stats.unmatched_sections) || !integer(value.stats.unaligned_changes) || !Array.isArray(value.rows) || value.rows.length > 160 || !Array.isArray(value.alignment_basis)) return null;
  const seen = new Set<string>();
  for (const row of value.rows) {
    if (!object(row) || typeof row.change_id !== "string" || !hash.test(row.change_id) || seen.has(row.change_id) || typeof row.label !== "string" || row.label.length > 120 || !["added", "removed", "modified"].includes(String(row.kind)) || typeof row.aligned !== "boolean" || !side(row.old) || !side(row.new) || row.old === null && row.new === null || !Array.isArray(row.questions) || row.questions.length > 4 || !row.questions.every(item => typeof item === "string" && item.length <= 300)) return null;
    if (row.impact !== null && (!object(row.impact) || typeof row.impact.quote !== "string" || ![row.old, row.new].some(item => item && item.citation_id === (row.impact as Record<string, unknown>).citation_id && item.quote.includes((row.impact as Record<string, unknown>).quote as string)))) return null;
    seen.add(row.change_id);
  }
  if (value.stats.changes < value.rows.length || value.alignment_basis.length > 200 || !value.alignment_basis.every(item => object(item) && typeof item.sheet === "string" && typeof item.key_header === "string")) return null;
  if (value.complete && (value.stats.changes !== value.rows.length || value.stats.unmatched_sections > 0 || value.stats.unaligned_changes > 0)) return null;
  if (value.unmatched !== undefined && (!Array.isArray(value.unmatched) || value.unmatched.length > 8000 || !value.unmatched.every(item => object(item) && typeof item.reason === "string" && (item.sheet === undefined || typeof item.sheet === "string") && (item.citation_id === undefined || typeof item.citation_id === "string" && uuid.test(item.citation_id)) && (item.count === undefined || integer(item.count))))) return null;
  if (value.complete && Array.isArray(value.unmatched) && value.unmatched.length > 0) return null;
  if (value.citation_ids !== undefined && (!Array.isArray(value.citation_ids) || value.citation_ids.length !== 2 || !value.citation_ids.every(item => typeof item === "string" && uuid.test(item)))) return null;
  return value as unknown as Comparison;
}
function Value({ value }: { value: Side | null }) {
  if (!value) return <span className="text-muted-foreground">无对应内容</span>;
  const native = value.locator.native;
  function location(item: string) {
    const page = /^page:([1-9]\d*)$/.exec(item), line = /^line:([1-9]\d*)$/.exec(item);
    if (page) return `第 ${page[1]} 页`;
    if (line) return `第 ${line[1]} 行`;
    if (item.startsWith("cell:")) {
      try { const cell: unknown = JSON.parse(item.slice(5)); if (Array.isArray(cell) && cell.length === 2 && cell.every(value => typeof value === "string")) return `${cell[0]}!${cell[1]}`; } catch { /* Keep the supplied location as text. */ }
    }
    return item;
  }
  const label = Array.isArray(native) ? native.filter((item): item is string => typeof item === "string").slice(0, 2).map(location).join(" · ") : Number.isInteger(value.locator.line_start) ? `第 ${value.locator.line_start} 行` : "固定定位";
  return <><p className="whitespace-pre-wrap break-words">{value.quote}</p><small className="text-muted-foreground">{label}{value.value_kind === "formula" ? " · 公式原文（未计算）" : ""}</small></>;
}

export function AnswerComparison({ value }: { value: unknown }) {
  const data = comparison(value);
  if (!data) return value == null ? null : <p role="alert" className="text-sm text-muted-foreground">比较结果暂不可核对，请重新读取原记录。</p>;
  const reasons: Record<string, string> = { ambiguous_headers: "表头不唯一或超出可核对范围", ambiguous_row_keys: "作为行标识的首列有空值或重复", row_key_header_missing: "缺少原版使用的行标识列", cell_without_header: "部分单元格没有对应表头", cell_too_large: "部分单元格内容超出本次可核对范围", incomplete_parse: "解析覆盖尚不完整", different_parsed_formats: "两份资料的解析格式不同", comparison_size_limit: "资料超出当前比较体积", comparison_unit_limit: "资料段落或单元格数量超出当前范围" };
  return <section aria-label="固定版本资料比较" className="space-y-2">
    <p className="text-sm">差异 · 已核对 {data.rows.length} / {data.stats.changes} 处变化</p>
    {!data.complete && <p role="status" className="text-sm text-muted-foreground">比较尚未完整，未读取、未对齐或未完整解析的部分仍待核对，不能视为无变化。</p>}
    {data.stats.unmatched_sections > 0 && <p className="text-sm text-muted-foreground">另有 {data.stats.unmatched_sections} 处解析或对齐缺口。</p>}
    {!!data.unmatched?.length && <ul aria-label="未完成核对的部分" className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">{data.unmatched.slice(0, 20).map((item, index) => <li key={index} className="break-words">{item.citation_id && data.citation_ids ? item.citation_id === data.citation_ids[0] ? "旧版" : "新版" : "资料"}{item.sheet ? ` · ${item.sheet}` : ""}：{reasons[item.reason] || "尚待核对"}{item.count && item.count > 1 ? `（${item.count} 处）` : ""}</li>)}{data.unmatched.length > 20 && <li>其余缺口保留在本次实际结果记录中。</li>}</ul>}
    {data.alignment_basis.length > 0 && <p className="break-words text-xs text-muted-foreground">表格按表头及原版首列唯一值对齐：{Array.from(new Set(data.alignment_basis.map(item => `${item.sheet} · ${item.key_header}`))).join("；")}</p>}
    {data.rows.length > 0 && <p className="text-xs text-muted-foreground sm:hidden">左右滑动查看其余列。</p>}
    {data.rows.length === 0 ? <p className="text-sm">{data.complete ? "已解析并对齐的内容未发现值差异。" : "尚无完整核对的差异行。"}</p> : <div className="max-w-full overflow-x-auto rounded-lg border border-border" role="region" aria-label="差异表，可横向滚动" tabIndex={0}>
      <table className="w-full min-w-[40rem] table-fixed text-left text-sm">
        <caption className="sr-only">固定版本变化、两侧原文、文中影响依据与待确认事项</caption>
        <thead className="border-b border-border bg-muted/40"><tr>{["变化项", "旧版原文", "新版原文", "文中影响依据", "待确认"].map(title => <th key={title} scope="col" className="px-3 py-2 font-medium">{title}</th>)}</tr></thead>
        <tbody>{data.rows.map(row => <tr key={row.change_id} className="border-b border-border align-top last:border-0">
          <th scope="row" className="break-words px-3 py-2 font-medium">{row.label}<small className="block font-normal text-muted-foreground">{!row.aligned ? "未能对齐" : row.kind === "added" ? "新增" : row.kind === "removed" ? "删除" : "修改"}</small></th>
          <td className="px-3 py-2"><Value value={row.old}/></td><td className="px-3 py-2"><Value value={row.new}/></td>
          <td className="whitespace-pre-wrap break-words px-3 py-2">{row.impact?.quote || "待确认"}</td>
          <td className="break-words px-3 py-2">{row.questions.length ? row.questions.join("；") : "待确认"}</td>
        </tr>)}</tbody>
      </table>
    </div>}
  </section>;
}
