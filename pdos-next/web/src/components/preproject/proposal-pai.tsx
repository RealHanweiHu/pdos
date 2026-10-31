"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Xiaopai } from "@/components/xiaopai";
import { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";
import type { MaterialContext } from "@/components/category-material-editor";
import { X } from "@phosphor-icons/react";
import styles from "./proposal-document.module.css";

export function ProposalPai({ categoryId, proposalId, principalId, proposalTitle, materialContext, onClose }: {
  onClose?: () => void;
  categoryId: string; proposalId: string; principalId: string; proposalTitle?: string; materialContext?: MaterialContext;
}) {
  const [compose, setCompose] = useState(false);
  const transport = useMemo(() => categoryTransport(categoryId, browserApi), [categoryId]);
  return <section className={styles.pai} aria-label="当前提案的小Pai">
    {<div className={styles.paiBody}><Xiaopai headerActions={onClose && <Button size="icon" variant="ghost" aria-label="关闭提案小Pai" onClick={onClose}><X/></Button>} key={`${principalId}:${categoryId}:${proposalId}`} api={transport}
      categoryId={categoryId} principalId={principalId} proposalId={proposalId} proposalTitle={proposalTitle}
      materialContext={materialContext} productId="" sources={[]} composeOpen={compose} onComposeChange={setCompose} /></div>}
  </section>;
}
