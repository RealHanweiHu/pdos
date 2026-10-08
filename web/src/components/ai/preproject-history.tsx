"use client";

import { Dialog } from "radix-ui";
import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { proposalKinds, proposalStateLabels, type Proposal } from "@/components/product-work/proposal-types";

export function PreprojectHistory({ categoryId, disabled, onDenied }: { categoryId: string; disabled: boolean; onDenied: (message: string, status: number) => void }) {
  const [open, setOpen] = useState(false), [loading, setLoading] = useState(false), [items, setItems] = useState<Proposal[]>([]), [error, setError] = useState("");
  const descriptionId = useId();
  async function show() {
    setOpen(true); setLoading(true); setError(""); setItems([]);
    try {
      const response = await fetch(`/api/product-work/spaces/${categoryId}/proposals`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) {
        const message = data.detail?.message ?? "提案暂时无法读取";
        if ([401, 403].includes(response.status)) onDenied(message, response.status);
        throw new Error(message);
      }
      setItems(data.items);
    } catch (e) { setError(e instanceof Error ? e.message : "提案暂时无法读取"); }
    finally { setLoading(false); }
  }
  return <><Button variant="ghost" size="sm" disabled={disabled} onClick={() => void show()}>已有提案</Button>
    <Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-black/50"/><Dialog.Content aria-describedby={descriptionId} className="fixed left-1/2 top-1/2 z-[60] max-h-[85dvh] w-[calc(100%_-_2rem)] max-w-xl -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border bg-background p-6 shadow-xl">
      <Dialog.Title className="text-lg font-semibold">当前品类的已有提案</Dialog.Title><Dialog.Description id={descriptionId} className="mt-2 text-sm text-muted-foreground">仅列出你有权查看的提案。客户资料保留在对应提案中。</Dialog.Description>
      <div className="my-5 space-y-3">{loading ? <p role="status">正在读取…</p> : error ? <p role="alert" className="text-sm text-destructive">{error}</p> : items.length ? items.map(p => <a key={p.id} className="block rounded-lg border p-4 hover:bg-muted" href={`/product-work?category=${categoryId}&tab=proposals&proposal=${p.id}`}><span className="block text-sm font-medium">{p.title}</span><span className="mt-1 block text-xs text-muted-foreground">{proposalKinds[p.entry_kind].label} · {proposalStateLabels[p.state] ?? p.state}</span></a>) : <p className="text-sm text-muted-foreground">暂无可访问提案，直接在对话中说出新的产品需求。</p>}</div>
      <Dialog.Close asChild><Button variant="outline">返回对话</Button></Dialog.Close>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </>;
}
