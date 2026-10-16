"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Xiaopai } from "@/components/xiaopai";
import { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";

export function ProposalPai({ categoryId, proposalId, principalId }: {
  categoryId: string; proposalId: string; principalId: string;
}) {
  const [open, setOpen] = useState(false);
  const [compose, setCompose] = useState(false);
  const transport = useMemo(() => categoryTransport(categoryId, browserApi), [categoryId]);
  return <section className="space-y-3" aria-label="当前提案的小Pai">
    <Button variant="outline" aria-expanded={open} onClick={() => setOpen(value => !value)}>
      {open ? "收起提案小Pai" : "用小Pai起草或查漏"}
    </Button>
    {open && <Xiaopai key={`${principalId}:${categoryId}:${proposalId}`} api={transport}
      categoryId={categoryId} principalId={principalId} proposalId={proposalId}
      productId="" sources={[]} composeOpen={compose} onComposeChange={setCompose} />}
  </section>;
}
