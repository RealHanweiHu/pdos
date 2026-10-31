"use client";

import { useEffect, useState } from "react";
import { PaiDocumentCard } from "@/components/pai-conversation";
import { adoptedCategory, asCandidate } from "./contracts";
import type { Api, CategoryAdopted, CategoryCandidate, CreatedCategory } from "./contracts";

type Event = { sequence: number; event: unknown };
type Adoption = { proof: CategoryAdopted; category: CreatedCategory };

export function PersonalRunMaterials({ api, runId, onOpenCandidate, onOpenCategory, onUnavailable }: {
  api: Api;
  runId: string;
  onOpenCandidate: (runId: string, candidate: CategoryCandidate) => void;
  onOpenCategory: (runId: string, proof: CategoryAdopted, category: CreatedCategory) => void;
  onUnavailable: () => void;
}) {
  const [reading, setReading] = useState<{ runId: string; candidates: CategoryCandidate[]; adoptions: Adoption[]; error: string } | null>(null);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      try {
        const events: Event[] = [];
        let after = 0;
        for (;;) {
          const page = await api<{ items: Event[]; next_cursor: number }>(`v1/personal/agent-runs/${runId}/events?after=${after}&page_size=200`);
          events.push(...page.items);
          if (page.items.length < 200 || page.next_cursor <= after) break;
          after = page.next_cursor;
        }
        const candidates = events.flatMap(item => { const candidate = asCandidate(item.event); return candidate ? [candidate] : []; });
        const proofs = events.flatMap(item => { const proof = adoptedCategory(item.event, runId); return proof ? [proof] : []; });
        let directory: CreatedCategory[] = [];
        if (proofs.length) {
          try { directory = await api<CreatedCategory[]>("v1/categories"); } catch { /* The saved receipt still opens by its stable identity. */ }
        }
        if (!active) return;
        const adoptions = proofs.map(proof => {
          const candidate = candidates.find(item => item.candidate_digest === proof.candidate_digest);
          const saved = directory.find(item => item.id === proof.category_id);
          return { proof, category: { id: proof.category_id, name: saved?.name ?? candidate?.input.name ?? "已创建品类", purpose: saved?.purpose ?? candidate?.input.purpose ?? "", receiptId: proof.receipt_id } };
        });
        const adoptedDigests = new Set(adoptions.map(item => item.proof.candidate_digest));
        setReading({ runId, candidates: candidates.filter(item => !adoptedDigests.has(item.candidate_digest)), adoptions, error: "" });
      } catch (failure) {
        if (!active) return;
        if ([401, 403].includes((failure as { status?: number }).status ?? 0)) onUnavailable();
        else setReading({ runId, candidates: [], adoptions: [], error: failure instanceof Error ? failure.message : "历史成果暂不可读。" });
      }
    });
    return () => { active = false; };
  }, [api, runId, onUnavailable]);
  const current = reading?.runId === runId ? reading : null;
  if (!current) return <p className="subtle" role="status">正在恢复本次成果…</p>;
  if (current.error) return <p role="alert">{current.error}</p>;
  return <>{current.adoptions.map(({ proof, category }) => <PaiDocumentCard key={proof.receipt_id} title={category.name} metadata="品类 · 已保存" action="返回编辑" onOpen={() => onOpenCategory(runId, proof, category)} />)}
    {current.candidates.map(candidate => <PaiDocumentCard key={candidate.candidate_digest} title={candidate.input.name} metadata="品类 · 小Pai 起草 · 待确认" action="查看与编辑" onOpen={() => onOpenCandidate(runId, candidate)} />)}</>;
}
