"use client";

import { type ReactNode } from "react";

export function ReadingPanel({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return <section className="panel"><header className="mb-4 flex items-center justify-between gap-3"><h3 className="font-semibold">{title}</h3>{count !== undefined && <span className="subtle font-mono">{count}</span>}</header>{children}</section>;
}

export function ReadingRecord({ id, title, meta, children, open }: { id: string; title: string; meta: ReactNode; children: ReactNode; open?: boolean }) {
  return <details id={id} open={open} className="min-w-0 scroll-mt-20 rounded-lg border border-border p-4"><summary className="cursor-pointer break-words font-medium focus-visible:rounded-lg"><span>{title}</span><span className="subtle mt-1 block">{meta}</span></summary><div className="min-w-0 space-y-4 border-t border-border pt-4 mt-4">{children}</div></details>;
}
