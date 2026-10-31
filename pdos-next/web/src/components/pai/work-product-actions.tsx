"use client";

import { FileText, Table as TableIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { hasDocumentResult, hasTableResult, latestWorkProduct, type WorkProduct, type WorkProductRun } from "@/lib/work-products";

export function WorkProductActions({ run, items, busy, onOpen }: {
  run: WorkProductRun;
  items: WorkProduct[];
  busy: boolean;
  onOpen: (kind: WorkProduct["kind"]) => void;
}) {
  if (!hasDocumentResult(run)) return null;
  const document = latestWorkProduct(items, run.run_id, "document");
  const table = latestWorkProduct(items, run.run_id, "table");
  return <div className="flex flex-wrap gap-2" aria-label="打开回复成果">
    <Button size="sm" variant="ghost" disabled={busy} onClick={() => onOpen("document")}><FileText size={14} aria-hidden="true" />{document ? "打开文档" : "保存为文档"}</Button>
    {hasTableResult(run) && <Button size="sm" variant="ghost" disabled={busy} onClick={() => onOpen("table")}><TableIcon size={14} aria-hidden="true" />{table ? "打开表格" : "保存为表格"}</Button>}
  </div>;
}
