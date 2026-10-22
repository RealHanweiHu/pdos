export type PlanItemStatus = "done" | "partial" | "blocked" | "todo";

export type PlanItem = {
  id: string;
  title: string;
  status: PlanItemStatus;
  group: string;
  groupLabel: string;
  anchor: string;
  summary: string;
  dependencies: string;
  responsibility: string;
};

export type PlanGroup = { id: string; label: string; items: PlanItem[] };

export type PlanLoop = { title: string; anchor: string; itemIds: string[]; note: string; items: PlanItem[] };

export type PlanNextArea = { label: string; ready: string; gaps: string };

export type PlanStep = { order: string; action: string; result: string };

export type PlanCounts = { total: number; done: number; partial: number; blocked: number; todo: number };

export type PlanProgress = {
  version: string;
  counts: PlanCounts;
  items: PlanItem[];
  groups: PlanGroup[];
  loops: PlanLoop[];
  nextAreas: PlanNextArea[];
  steps: PlanStep[];
  notes: { candidate: string; focus: string; blocker: string; incident: string };
};

export const planStatusLabels: Record<PlanItemStatus, string> = { done: "已完成", partial: "部分完成", blocked: "外部阻塞", todo: "待完成" };

export const planStatusOrder: PlanItemStatus[] = ["done", "partial", "todo", "blocked"];

const statuses: Record<string, PlanItemStatus> = { x: "done", "~": "partial", "!": "blocked", " ": "todo" };

/** Display text keeps link labels but drops repo-relative targets and inline marks that cannot render in the browser. */
export function planCleanText(value: string): string {
  return value.replace(/\[([^\]]+)\]\([^)]*\)/g, "$1").replace(/\*\*/g, "").replace(/`/g, "").trim();
}

function expandIds(text: string): string[] {
  const ids: string[] = [];
  for (const raw of text.split(/[、，,;；]/)) {
    const segment = raw.trim();
    if (!segment) continue;
    const range = segment.match(/^([NPQ]\d?-\d+)～(\d+)$/);
    if (range) {
      const base = range[1];
      const dash = base.lastIndexOf("-");
      const prefix = base.slice(0, dash + 1);
      const width = base.length - dash - 1;
      const start = Number(base.slice(dash + 1));
      const end = Number(range[2]);
      for (let index = start; index <= end && index - start < 80; index += 1) ids.push(`${prefix}${String(index).padStart(width, "0")}`);
      continue;
    }
    ids.push(segment);
  }
  return ids;
}

function tableCells(line: string): string[] | null {
  if (!line.startsWith("|") || !line.endsWith("|")) return null;
  const cells = line.split("|").slice(1, -1).map((cell) => cell.trim());
  return cells.length > 0 && cells.every((cell) => cell === "" || /^:?-{3,}:?$/.test(cell)) ? null : cells;
}

export function parsePlanProgress(markdown: string): PlanProgress {
  const items: PlanItem[] = [];
  const groups: PlanGroup[] = [];
  const loops: PlanLoop[] = [];
  const nextAreas: PlanNextArea[] = [];
  const steps: PlanStep[] = [];
  const notes = { candidate: "", focus: "", blocker: "", incident: "" };
  let group: PlanGroup | null = null;
  let anchor = "";
  let item: PlanItem | null = null;
  let section = "";
  let subsection = "";
  let tableMode: "" | "loops" | "areas" | "steps" = "";
  let version = "";

  for (const line of markdown.split(/\r?\n/)) {
    const title = line.match(/^# .*清单 v(\S+)\s*$/);
    if (title) version = title[1];
    const anchorLine = line.match(/^<a id="([^"]+)"><\/a>$/);
    if (anchorLine) { anchor = anchorLine[1]; item = null; tableMode = ""; continue; }
    const heading = line.match(/^## (.+)$/);
    if (heading) {
      section = heading[1]; subsection = ""; item = null; tableMode = "";
      const matched = heading[1].match(/^((?:N\d)|P|Q) · (.+)$/);
      group = matched ? { id: matched[1], label: matched[2], items: [] } : null;
      if (group) groups.push(group);
      continue;
    }
    const sub = line.match(/^### (.+)$/);
    if (sub) { subsection = sub[1]; item = null; tableMode = ""; continue; }
    const entry = line.match(/^- \[([ x~!])\] \*\*(.+?)\*\*\s*$/);
    if (entry && group) {
      const name = entry[2];
      const split = name.split(/[:：]/);
      item = { id: split[0].trim(), title: split.slice(1).join("：").trim(), status: statuses[entry[1]] ?? "todo", group: group.id, groupLabel: group.label, anchor, summary: "", dependencies: "", responsibility: "" };
      items.push(item); group.items.push(item);
      continue;
    }
    if (item) {
      const field = line.match(/^ {2}- (当前摘要|依赖|业务责任)[:：](.*)$/);
      if (field) {
        const value = planCleanText(field[2]);
        if (field[1] === "当前摘要" && !item.summary) item.summary = value;
        if (field[1] === "依赖" && !item.dependencies) item.dependencies = value;
        if (field[1] === "业务责任" && !item.responsibility) item.responsibility = value;
      }
    }
    const cells = tableCells(line);
    if (cells) {
      if (section.startsWith("未完成工作") && !subsection && cells.length === 3) {
        const loopCell = cells[0].match(/^\[([^\]]+)\]\(#([^)]+)\)$/);
        if (loopCell) { loops.push({ title: loopCell[1], anchor: loopCell[2], itemIds: expandIds(cells[1]), note: planCleanText(cells[2]), items: [] }); continue; }
        if (cells[0] === "功能闭环") tableMode = "loops";
        continue;
      }
      if (subsection.startsWith("PDOS Next · 当前业务交付")) {
        if (cells[0] === "范围") { tableMode = "areas"; continue; }
        if (cells[0] === "顺序") { tableMode = "steps"; continue; }
        if (tableMode === "areas" && cells.length === 3 && /^G\d /.test(cells[0])) { nextAreas.push({ label: cells[0], ready: planCleanText(cells[1]), gaps: planCleanText(cells[2]) }); continue; }
        if (tableMode === "steps" && cells.length === 3 && /^\d+$/.test(cells[0])) { steps.push({ order: cells[0], action: planCleanText(cells[1]), result: planCleanText(cells[2]) }); continue; }
      }
      continue;
    }
    const note = line.match(/^\*\*(最新已登记候选|当前主交付|当前阻塞与恢复条件|数据库与事故边界)(?:\*\*)?[:：](.*)$/);
    if (note) {
      const value = planCleanText(note[2]);
      if (note[1] === "最新已登记候选" && !notes.candidate) notes.candidate = value;
      if (note[1] === "当前主交付" && !notes.focus) notes.focus = value;
      if (note[1] === "当前阻塞与恢复条件" && !notes.blocker) notes.blocker = value;
      if (note[1] === "数据库与事故边界" && !notes.incident) notes.incident = value;
    }
  }

  const byId = new Map(items.map((entry2) => [entry2.id, entry2]));
  for (const loop of loops) loop.items = loop.itemIds.map((id) => byId.get(id)).filter((entry2): entry2 is PlanItem => Boolean(entry2));
  const counts = { total: items.length, done: 0, partial: 0, blocked: 0, todo: 0 };
  for (const entry2 of items) counts[entry2.status] += 1;
  return { version, counts, items, groups, loops, nextAreas, steps, notes };
}
