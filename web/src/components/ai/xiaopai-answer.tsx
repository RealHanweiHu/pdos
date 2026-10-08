type TextBlock = { kind: "text"; content: string };
type TableBlock = { kind: "table"; headers: string[]; rows: string[][] };

function cells(line: string) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map(cell => cell.trim().replace(/\\\|/g, "|"));
}

function blocks(answer: string): (TextBlock | TableBlock)[] {
  const lines = answer.split("\n"), result: (TextBlock | TableBlock)[] = [];
  let text: string[] = [];
  const flush = () => { if (text.length) result.push({ kind: "text", content: text.join("\n") }); text = []; };
  for (let index = 0; index < lines.length; index++) {
    if (lines[index].trim().startsWith("|") && /^\|(?:\s*:?-{3,}:?\s*\|)+$/.test(lines[index + 1]?.trim() ?? "")) {
      const headers = cells(lines[index]), rows: string[][] = [];
      let end = index + 2;
      while (end < lines.length && lines[end].trim().startsWith("|") && cells(lines[end]).length === headers.length) rows.push(cells(lines[end++]));
      if (rows.length) { flush(); result.push({ kind: "table", headers, rows }); index = end - 1; continue; }
    }
    text.push(lines[index]);
  }
  flush();
  return result;
}

export function XiaopaiAnswer({ answer, researchDraft = false }: { answer: string; researchDraft?: boolean }) {
  return <div className="space-y-3">
    {researchDraft && <p className="text-xs text-muted-foreground">AI 研究草稿 · 已附来源，热度、现价与测试口径待核实</p>}
    {blocks(answer).map((block, index) => block.kind === "text" ? <p key={index} className="whitespace-pre-wrap break-words text-sm leading-7">{block.content}</p> : <div key={index} className="max-w-full overflow-x-auto rounded-lg border"><table aria-label="研究资料对比" className="w-full min-w-[720px] border-collapse text-left text-xs leading-5"><thead className="bg-muted/70"><tr>{block.headers.map((header, column) => <th key={column} scope="col" className="min-w-24 border-b px-3 py-2 font-medium">{header}</th>)}</tr></thead><tbody>{block.rows.map((row, rowIndex) => <tr key={rowIndex} className="border-b last:border-b-0">{row.map((cell, column) => <td key={column} className="min-w-24 max-w-64 whitespace-pre-wrap break-words px-3 py-2 align-top">{cell}</td>)}</tr>)}</tbody></table></div>)}
  </div>;
}
