"use client";

import { FileXls, SpinnerGap } from "@phosphor-icons/react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import { type ExportFetch, exportSummary, readExport } from "./lib/export-download";

type ExportButtonProps = {
  exportUrl: string | null;
  label?: string;
  title?: string;
  fetcher?: ExportFetch;
};

function save(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** One export entry; the server decides rows, AI labels and the audit. */
export function ExportButton({ exportUrl, label = "导出 Excel", title, fetcher }: ExportButtonProps) {
  const [state, setState] = useState<{ busy: boolean; note: string; failed: boolean }>({ busy: false, note: "", failed: false });
  const run = async () => {
    if (!exportUrl || state.busy) return;
    setState({ busy: true, note: "正在按你的查看权限生成…", failed: false });
    try {
      const result = await readExport(fetcher ?? ((input, init) => fetch(input, init)), exportUrl);
      save(result.blob, result.filename);
      setState({ busy: false, note: exportSummary(result), failed: false });
    } catch (error) {
      setState({ busy: false, note: error instanceof Error ? error.message : "导出未完成。", failed: true });
    }
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <Button type="button" size="sm" variant="outline" disabled={!exportUrl || state.busy} aria-busy={state.busy} title={title ?? "按你当前的查看权限导出；AI 起草的内容会逐条标注，导出会留审计记录。"} onClick={() => void run()}>
        {state.busy ? <SpinnerGap className="animate-spin" /> : <FileXls />}
        {label}
      </Button>
      <span role={state.failed ? "alert" : "status"} aria-live="polite" className={state.failed ? "text-xs text-destructive" : "text-xs text-muted-foreground"}>
        {state.note}
      </span>
    </span>
  );
}
