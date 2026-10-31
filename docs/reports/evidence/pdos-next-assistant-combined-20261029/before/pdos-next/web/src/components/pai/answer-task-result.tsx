type Source = { citation_id: string; source_revision: number; currentness?: string; read_basis_status?: string };
type Cell = { status: "recorded" | "not_recorded" | "to_confirm" | "unspecified"; text: string; content_kind?: "analysis" | "recorded"; basis_text?: string; citation_id?: string; source_revision?: number; locator?: Record<string, unknown> };
type Result = { version: 1; format: string; title: string; columns: { key: string; label: string }[]; rows: { cells: Record<string, Cell> }[]; verified: boolean; unknown_count: number };
const formats: Record<string, { title: string; columns: [string, string][] }> = {
  blockers: { title: "阻塞清单", columns: [["conclusion", "当前结论"], ["blocker", "阻塞事项"], ["owner", "责任人"], ["next_step", "下一步"], ["decision", "待决定事项"]] },
  cases: { title: "案例表", columns: [["case", "相似案例"], ["root_cause", "根因"], ["measures", "措施"], ["verification", "验证结果"], ["conditions_and_differences", "适用条件与差异"]] },
  review: { title: "评审清单", columns: [["key_changes", "关键变化"], ["unresolved_issues", "未解决问题"], ["decisions", "需决定事项"]] },
  commitments: { title: "承诺表", columns: [["current_commitment", "当前承诺"], ["deviation", "偏差"], ["related_objects", "相关对象"], ["follow_up", "需跟进事项"]] },
};
const unknowns: Record<string, string> = { not_recorded: "未记录", to_confirm: "待确认", unspecified: "未指定" };
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
function result(value: unknown, sources: Source[]): Result | null {
  if (!object(value) || value.version !== 1 || typeof value.format !== "string" || !Object.hasOwn(formats, value.format) || typeof value.verified !== "boolean" || !Number.isSafeInteger(value.unknown_count) || Number(value.unknown_count) < 0) return null;
  const registered = formats[value.format];
  if (value.title !== registered.title || !Array.isArray(value.columns) || value.columns.length !== registered.columns.length || !value.columns.every((column, i) => object(column) && column.key === registered.columns[i][0] && column.label === registered.columns[i][1]) || !Array.isArray(value.rows) || value.rows.length < 1 || value.rows.length > 40) return null;
  let unknownCount = 0;
  for (const row of value.rows) {
    if (!object(row) || !object(row.cells) || Object.keys(row.cells).length !== registered.columns.length) return null;
    for (const [key] of registered.columns) {
      const cell = row.cells[key];
      if (!object(cell) || typeof cell.text !== "string" || cell.text.length < 1 || Array.from(cell.text).length > 1000) return null;
      if (cell.status === "recorded") {
        if (typeof cell.citation_id !== "string" || !sources.some(source => source.citation_id === cell.citation_id && source.source_revision === cell.source_revision) || !object(cell.locator) || !["analysis", "recorded"].includes(String(cell.content_kind)) || typeof cell.basis_text !== "string" || !cell.basis_text || Array.from(cell.basis_text).length > 1000 || cell.content_kind === "recorded" && cell.text !== cell.basis_text || key === "owner" && cell.content_kind !== "recorded") return null;
      } else {
        if (typeof cell.status !== "string" || !Object.hasOwn(unknowns, cell.status) || cell.text !== unknowns[cell.status] || cell.citation_id !== undefined || key === "owner" && cell.status !== "unspecified") return null;
        unknownCount++;
      }
    }
  }
  return unknownCount === value.unknown_count ? value as unknown as Result : null;
}

function location(value: Cell["locator"]) {
  if (!value) return "固定记录";
  if (typeof value.json_pointer === "string") return "登记字段";
  if (Number.isInteger(value.line_start)) return `第 ${value.line_start} 行`;
  return "固定片段";
}

export function AnswerTaskResult({ value, sources, onSource }: { value: unknown; sources: Source[]; onSource?: () => void }) {
  const data = result(value, sources);
  if (!data) return value == null ? null : <p role="alert" className="text-sm text-muted-foreground">任务结果暂不可核对，请重新读取原记录。</p>;
  return <section aria-label={data.title} className="space-y-2">
    <p className="text-sm font-medium">{data.title}</p>
    {!data.verified && <p role="status" className="text-sm text-muted-foreground">部分单元格未通过引用核对，已标为待确认。</p>}
    {data.unknown_count > 0 && <p className="text-xs text-muted-foreground">{data.unknown_count} 项未记录或待确认；责任人与日期以已有登记为准。</p>}
    <p className="text-xs text-muted-foreground sm:hidden">左右滑动查看其余列。</p>
    <div className="max-w-full overflow-x-auto rounded-lg border border-border" role="region" aria-label={`${data.title}，可横向滚动`} tabIndex={0}>
      <table className="w-full min-w-[36rem] table-fixed text-left text-sm">
        <caption className="sr-only">{data.title}，每项保留来源或明确的未知状态</caption>
        <thead className="border-b border-border bg-muted/40"><tr>{data.columns.map(column => <th key={column.key} scope="col" className="px-3 py-2 font-medium">{column.label}</th>)}</tr></thead>
        <tbody>{data.rows.map((row, index) => <tr key={index} className="border-b border-border align-top last:border-0">{data.columns.map(column => {
          const cell = row.cells[column.key], sourceIndex = sources.findIndex(source => source.citation_id === cell.citation_id), source = sources[sourceIndex];
          return <td key={column.key} className="whitespace-pre-wrap break-words px-3 py-2">
            {cell.content_kind === "analysis" && <small className="mb-1 block text-muted-foreground">分析</small>}
            <p className={cell.status !== "recorded" ? "text-muted-foreground" : undefined}>{cell.text}</p>
            {cell.content_kind === "analysis" && <blockquote className="mt-2 border-l-2 border-border pl-2 text-xs text-muted-foreground">原文依据：{cell.basis_text}</blockquote>}
            {cell.status === "recorded" && <a href={`#assistant-source-${cell.citation_id}-${sourceIndex}`} onClick={onSource} className="text-xs text-muted-foreground underline underline-offset-4" aria-label={`查看第 ${index + 1} 行${column.label}的来源`}>来源 · v{cell.source_revision} · {location(cell.locator)}</a>}
            {source?.currentness === "updated" ? <small className="block text-muted-foreground">资料已更新，当前事实请重新查询</small> : source?.currentness === "history" ? <small className="block text-muted-foreground">历史版本</small> : null}
            {source?.read_basis_status === "needs_recheck" && <small className="block text-muted-foreground">当前适用性待重核</small>}
          </td>;
        })}</tr>)}</tbody>
      </table>
    </div>
  </section>;
}
