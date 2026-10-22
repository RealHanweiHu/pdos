"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Xiaopai } from "@/components/xiaopai";
import { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";
import { Sparkle } from "@phosphor-icons/react";
import styles from "./proposal-document.module.css";

export function ProposalPai({ categoryId, proposalId, principalId, proposalTitle }: {
  categoryId: string; proposalId: string; principalId: string; proposalTitle?: string;
}) {
  const [open, setOpen] = useState(true);
  const [compose, setCompose] = useState(false);
  const transport = useMemo(() => categoryTransport(categoryId, browserApi), [categoryId]);
  return <section className={styles.pai} aria-label="当前提案的小Pai">
    <header className={styles.paiHeading}><span className={styles.agent}><Sparkle size={15} aria-hidden="true"/>小Pai</span><h2>本案助手</h2><Button size="xs" variant="ghost" aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? "收起" : "展开"}</Button></header>
    {open && <div className={styles.paiBody}><Xiaopai key={`${principalId}:${categoryId}:${proposalId}`} api={transport}
      categoryId={categoryId} principalId={principalId} proposalId={proposalId} proposalTitle={proposalTitle}
      productId="" sources={[]} composeOpen={compose} onComposeChange={setCompose} /></div>}
  </section>;
}
