"use client";

import { useEffect, useState } from "react";
import { FileText } from "@phosphor-icons/react";
import type { browserApi } from "@/lib/browser-api";

type Api = typeof browserApi;
type Proposal = { id: string; title: string; status: string; revision: number; owner_id: string; visibility: string };
const statusLabels: Record<string, string> = { draft: "草稿", returned: "已退回", in_review: "G0 评审中", approved: "已立项", rejected: "不立项", withdrawn: "已撤回" };
const visibilityLabels: Record<string, string> = { private: "私有提案", category: "品类共享", audience: "指定受众" };

export function ProposalList({ categoryId, api }: { categoryId: string; api: Api }) {
  const [proposals, setProposals] = useState<Proposal[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void api<{ items: Proposal[] }>(`v1/categories/${categoryId}/proposals?page_size=50`)
      .then(result => { if (active) setProposals(result.items); })
      .catch(failure => { if (active) setError((failure as Error).message); });
    return () => { active = false; };
  }, [api, categoryId]);

  if (error) return <p role="alert" className="workspace-read-error">{error}</p>;
  if (!proposals) return <p role="status" className="subtle">正在读取提案…</p>;
  if (proposals.length === 0) return <p className="workspace-list-empty">尚无立项提案。与品类小Pai 对话起草第一份提案；提案默认私有。</p>;
  return <div>{proposals.map(item =>
    <a key={item.id} className="workspace-record-row no-underline" href={`/categories/${categoryId}/proposals/${item.id}`}>
      <FileText size={18} aria-hidden="true"/>
      <div className="min-w-0 flex-1">
        <p className="break-words font-medium">{item.title}</p>
        <p className="subtle">{visibilityLabels[item.visibility] ?? item.visibility}</p>
      </div>
      <span className="workspace-state">{statusLabels[item.status] ?? item.status}</span>
      <span className="workspace-revision">v{item.revision}</span>
    </a>)}
  </div>;
}
