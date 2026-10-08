"use client";

import { useEffect, useState, type ReactNode } from "react";
import { CaretRightIcon } from "@phosphor-icons/react";
import { cn } from "@/lib/utils";

export function ReadingPanel({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return <section className="min-w-0 overflow-hidden rounded-lg border bg-card"><header className="flex items-center justify-between gap-2 border-b bg-muted/60 px-3.5 py-2"><h2 className="text-xs font-semibold text-muted-foreground">{title}</h2>{count !== undefined && <span className="font-mono text-[11px] text-muted-foreground">{count}</span>}</header>{children}</section>;
}

export function ReadingRecord({ id, title, meta, action = "查看详情", tone, disabled, children, defaultOpen = false }: { id: string; title: string; meta: ReactNode; action?: string; tone?: "pending" | "ok" | "active"; disabled?: boolean; children: ReactNode; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => {
    const locate = () => { if (window.location.hash === `#${id}`) setOpen(true); };
    locate(); window.addEventListener("hashchange", locate);
    return () => window.removeEventListener("hashchange", locate);
  }, [id]);
  return <article id={id} className="scroll-mt-16 overflow-hidden rounded-lg border bg-card">
    <button type="button" disabled={disabled} aria-expanded={open} aria-controls={`${id}-detail`} className="flex min-h-11 w-full items-center gap-2.5 px-3.5 py-2.5 text-left hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring disabled:opacity-60" onClick={() => setOpen(!open)}>
      <span aria-hidden="true" className={cn("size-1.5 shrink-0 rounded-full", tone === "pending" ? "bg-pending" : tone === "ok" ? "bg-emerald-600 dark:bg-emerald-400" : "bg-primary")}/>
      <span className="min-w-0 flex-1"><span className="block break-words text-[13px] font-semibold">{title}</span><span className="mt-0.5 block text-[11px] leading-5 text-muted-foreground">{meta}</span></span>
      <span className="hidden shrink-0 text-xs font-medium text-primary sm:inline">{open ? "收起" : action}</span><CaretRightIcon aria-hidden="true" className={cn("size-3.5 shrink-0 text-muted-foreground", open && "rotate-90")}/>
    </button>
    <div id={`${id}-detail`} hidden={!open} className="min-w-0 border-t p-3.5">{children}</div>
  </article>;
}

export function ReadingLabel({ children }: { children: ReactNode }) { return <h3 className="mb-2.5 mt-5 text-xs font-semibold text-muted-foreground first:mt-0">{children}</h3>; }
