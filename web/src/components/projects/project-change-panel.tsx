"use client";

import { SupplierNoticeLinks } from "./supplier-notice-links";
import { ProjectDiscussionTopics } from "./project-discussion-topics";

import { ChangeDecisionSummary } from "./change-decision-summary";

import { ChangeQuietPolicy, ChangeQuietReview } from "./change-quiet-period";
import { ChangeExecutionTasks } from "./change-execution-tasks";
import { ChangeImpactScope, type ImpactScopeBasis } from "./change-impact-scope";
import { ChangeAnalysisPreparation } from "./change-analysis-preparation";
import { ChangeImpactGraph } from "./change-impact-graph";
import { ChangeCompliance } from "./change-compliance";
import { ContextKnowledge } from "@/components/knowledge/context-knowledge";

import { useCallback, useEffect, useState } from "react";

import { IdChangeImpactForm, IdChangeImpactReadout, type IdImpactAnalysis, type ProfessionalSource } from "./id-change-impact-form";
import { Button } from "@/components/ui/button";

type Ecr = {
  impact_scope?:ImpactScopeBasis|null;impact_scope_digest?:string;
  professional_sources?:ProfessionalSource[];professional_basis_digest?:string;
  source_finding_id?: string | null;
  analysis_digest?:string; impact_analysis?:IdImpactAnalysis|null; id_impact_basis_digest?:string; affected_bom_ids?:string[];
  id_design_sources?: { candidate_id:string;frozen_version:number;feedback_version:number;feedback:string;source_reference:string;routing_reason:string }[];
  id: string;
  code: string;
  title: string;
  reason: string | null;
  status: string;
  decision_note?: string | null;
};

type Ecn = {
  id: string;
  ecr_id: string;
  code: string;
  title: string;
  status: string;
};

type ChangeSnapshot = {
  bom_choices?:{id:string;code:string;name:string;version:number}[];
  ecrs: Ecr[];
  ecns: Ecn[];
};

type LoadState = "loading" | "ready" | "error";

type Props = {
  focusEcrId?: string;
  projectId: string;
  canEdit: boolean;
  canApprove: boolean;
};

// ECR walks request → impact_analysis → approval → approved/rejected. The
// panel offers only the transition the current status allows, so the UI can
// never suggest a step the server would refuse.
const ECR_STATUS_LABELS: Record<string, string> = {
  request: "已提出",
  impact_analysis: "影响分析中",
  approval: "待审批",
  approved: "已批准",
  rejected: "已驳回",
  cancelled: "已取消",
};

const ECN_STATUS_LABELS: Record<string, string> = {
  ecn: "已开立",
  effectivity_decision: "生效决策中",
  erp_handoff: "ERP 交接中",
  cancelled: "已取消",
};

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body?.detail?.message ?? "操作失败";
  } catch {
    return "操作失败";
  }
}

async function post(path: string, body: unknown): Promise<void> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) throw new Error(await readError(response));
}

/**
 * Engineering change governance: ECR through to ECN.
 *
 * The tab is called 「工程·变更」 but had no change surface at all — the ECR
 * chain has been in the backend since V1 and was unreachable from the app.
 */
export function ProjectChangePanel({ projectId, canEdit, canApprove, focusEcrId }: Props) {
  const [snapshot, setSnapshot] = useState<ChangeSnapshot>({ ecrs: [], ecns: [] });
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draftCode, setDraftCode] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftReason, setDraftReason] = useState("");
  const [reopenReasons,setReopenReasons]=useState<Record<string,string>>({});

  const reload = useCallback(async () => {
    const response = await fetch(`/api/projects/${projectId}/changes`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    setSnapshot({ ecrs: body.ecrs ?? [], ecns: body.ecns ?? [], bom_choices:body.bom_choices??[] });
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`/api/projects/${projectId}/changes`, {
          cache: "no-store",
        });
        if (!response.ok) throw new Error(await readError(response));
        const body = await response.json();
        if (cancelled) return;
        setSnapshot({ ecrs: body.ecrs ?? [], ecns: body.ecns ?? [], bom_choices:body.bom_choices??[] });
        setState("ready");
      } catch (failure) {
        if (cancelled) return;
        setError(failure instanceof Error ? failure.message : "变更记录暂不可用");
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(()=>{
    const id=window.location.hash.slice(1);
    if(snapshot.ecrs.some(ecr=>`ecr-${ecr.id}`===id)||snapshot.ecns.some(ecn=>`ecn-${ecn.id}`===id)) document.getElementById(id)?.scrollIntoView({block:"center"});
  },[snapshot.ecrs,snapshot.ecns]);

  const act = useCallback(
    async (operation: () => Promise<void>) => {
      setBusy(true);
      setError(null);
      try {
        await operation();
        await reload();
      } catch (failure) {
        setError(failure instanceof Error ? failure.message : "操作失败，请重试");
      } finally {
        setBusy(false);
      }
    },
    [reload],
  );

  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">正在加载工程变更…</p>;
  }

  if (state === "error") {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  const ecnsByEcr = new Map<string, Ecn[]>();
  for (const ecn of snapshot.ecns) {
    const bucket = ecnsByEcr.get(ecn.ecr_id) ?? [];
    bucket.push(ecn);
    ecnsByEcr.set(ecn.ecr_id, bucket);
  }

  return (
    <div className="space-y-6" data-testid="change-panel">
      <ChangeQuietPolicy projectId={projectId}/>
      {!focusEcrId && <ProjectDiscussionTopics projectId={projectId}/>}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {canEdit && !focusEcrId ? (
        <section className="space-y-2 rounded-md border p-3">
          <h3 className="text-sm font-semibold">提出工程变更（ECR）</h3>
          <div className="flex flex-wrap gap-2">
            <input
              aria-label="ECR 编号"
              className="h-9 w-40 rounded-md border px-2 text-sm"
              placeholder="ECR 编号"
              value={draftCode}
              onChange={(event) => setDraftCode(event.target.value)}
            />
            <input
              aria-label="ECR 标题"
              className="h-9 flex-1 rounded-md border px-2 text-sm"
              placeholder="变更标题"
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
            />
          </div>
          <textarea
            aria-label="变更原因"
            className="min-h-16 w-full rounded-md border p-2 text-sm"
            placeholder="变更原因"
            value={draftReason}
            onChange={(event) => setDraftReason(event.target.value)}
          />
          <Button
            size="sm"
            disabled={
              busy || !draftCode.trim() || !draftTitle.trim() || !draftReason.trim()
            }
            onClick={() =>
              void act(async () => {
                await post(`/api/projects/${projectId}/changes/ecrs`, {
                  code: draftCode.trim(),
                  title: draftTitle.trim(),
                  reason: draftReason.trim(),
                });
                setDraftCode("");
                setDraftTitle("");
                setDraftReason("");
              })
            }
          >
            提出变更
          </Button>
        </section>
      ) : null}

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">变更单</h3>
        {snapshot.ecrs.length === 0 ? (
          <p className="text-sm text-muted-foreground">尚无工程变更。</p>
        ) : (
          <ul className="space-y-3">
            {snapshot.ecrs.filter(ecr => !focusEcrId || ecr.id === focusEcrId).map((ecr) => {
              const ecns = ecnsByEcr.get(ecr.id) ?? [];
              const base = `/api/projects/${projectId}/changes/ecrs/${ecr.id}`;
              return (
                <li key={ecr.id} id={`ecr-${ecr.id}`} className="rounded-md border p-3">
                  <ContextKnowledge key={ecr.id} projectId={projectId} contextKind="change_request" entityId={ecr.id} />
                  {!!ecr.id_design_sources?.length && <details className="mb-2 text-xs"><summary className="cursor-pointer">ID冻结反馈来源</summary>{ecr.id_design_sources.map(source=><p className="mt-2 whitespace-pre-wrap" key={source.candidate_id}>冻结 v{source.frozen_version} · 反馈版本 v{source.feedback_version}：{source.feedback}（{source.source_reference}） · 转入依据：{source.routing_reason}</p>)}</details>}
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-sm">{ecr.code}</span>
                    <span className="font-medium">{ecr.title}</span>{ecr.source_finding_id && <a className="ml-2 text-xs text-primary underline" href={`/ai-review?finding=${ecr.source_finding_id}`}>查看会议建议与人审回执</a>}
                    <span className="text-xs text-muted-foreground">
                      {ECR_STATUS_LABELS[ecr.status] ?? ecr.status}
                    </span>
                    <span className="ml-auto flex flex-wrap gap-2">
                      {canEdit && ecr.status === "request" ? (
                        <Button
                          size="sm"
                          disabled={busy}
                          onClick={() => void act(() => post(`${base}/start-impact`, {}))}
                        >
                          开始影响分析
                        </Button>
                      ) : null}
                      {/* Approval is a separate permission: the person who
                          analysed the change must not also approve it. */}
                      {canApprove && ecr.status === "approval" ? (
                        <>
                          <Button
                            size="sm"
                            disabled={busy}
                            onClick={() =>
                              void act(() => post(`${base}/decide`, { outcome: "approved" }))
                            }
                          >
                            批准
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            onClick={() =>
                              void act(() => post(`${base}/decide`, { outcome: "rejected" }))
                            }
                          >
                            驳回
                          </Button>
                        </>
                      ) : null}
                    </span>
                  </div>
                  {!!ecr.professional_sources?.length&&<details className="my-2 text-xs"><summary className="cursor-pointer">专业资料与转入依据</summary>{ecr.professional_sources.map(source=><div className="mt-2 space-y-1" key={source.route_id}><a className="text-primary underline" href={source.kind==="engineering_review"?`/projects?project=${projectId}&tab=engineering&engineering_review_id=${source.source_id}`:`/projects?project=${projectId}&tab=quality&firmware_package_id=${source.source_id}`}>{source.title} · 资料 v{source.revision}</a><p>{source.ready?"来源版本仍有效":"来源已有新版或出处变化，需要修订后重新分析"}</p><p className="whitespace-pre-wrap">{source.scope}</p><p className="whitespace-pre-wrap">转入依据：{source.routing_reason}</p></div>)}</details>}
                  <ChangeExecutionTasks key={`${ecr.id}:${ecr.status}:${ecr.impact_scope_digest??"none"}`} projectId={projectId} ecrId={ecr.id} canEdit={canEdit} />
                  <SupplierNoticeLinks projectId={projectId} targetKind="ecr" targetId={ecr.id}/>
                  <ChangeImpactScope projectId={projectId} ecrId={ecr.id} canEdit={canEdit} onSaved={reload} />
                  <ChangeDecisionSummary key={`${ecr.id}:${ecr.status}:${ecr.analysis_digest}`} projectId={projectId} ecrId={ecr.id}/>
                  <ChangeQuietReview key={`${ecr.id}:${ecr.status}:${ecr.analysis_digest}`} projectId={projectId} ecrId={ecr.id}/>
                  <ChangeAnalysisPreparation projectId={projectId} ecrId={ecr.id} />
                  <ChangeImpactGraph key={`${ecr.id}:${ecr.impact_scope_digest??"none"}`} projectId={projectId} ecrId={ecr.id} />
                  <ChangeCompliance key={`compliance:${ecr.id}:${ecr.impact_scope_digest ?? "none"}`} projectId={projectId} ecrId={ecr.id} canEdit={canEdit} />
                  {ecr.impact_analysis && <IdChangeImpactReadout analysis={ecr.impact_analysis}/>}
                  {canEdit && ecr.status === "impact_analysis" && <IdChangeImpactForm projectId={projectId} ecrId={ecr.id} key={`${ecr.id}:${ecr.id_impact_basis_digest??"general"}:${ecr.professional_basis_digest??"none"}:${ecr.impact_scope_digest??"none"}`} initialAnalysis={ecr.impact_analysis} impactScope={ecr.impact_scope} impactScopeDigest={ecr.impact_scope_digest} professionalSources={ecr.professional_sources} professionalBasisDigest={ecr.professional_basis_digest} sources={ecr.id_design_sources??[]} basisDigest={ecr.id_impact_basis_digest} boms={snapshot.bom_choices??[]} affectedBomIds={ecr.affected_bom_ids??[]} busy={busy} submit={body=>void act(()=>post(`${base}/submit-impact`,body))}/>}
                  {canEdit && ecr.status === "approval" && <div className="my-2 space-y-2"><label className="block text-xs">重新分析原因<textarea className="mt-1 w-full rounded-md border bg-background p-2 text-sm" maxLength={2048} disabled={busy} value={reopenReasons[ecr.id]??""} onChange={event=>setReopenReasons({...reopenReasons,[ecr.id]:event.target.value})}/></label><Button type="button" size="sm" variant="outline" disabled={busy||!reopenReasons[ecr.id]?.trim()||!ecr.analysis_digest} onClick={()=>void act(()=>post(`${base}/refresh-impact`,{expected_digest:ecr.analysis_digest,reason:reopenReasons[ecr.id]}))}>退回重新分析</Button></div>}
                  {ecr.reason ? (
                    <p className="mt-1 text-sm text-muted-foreground">{ecr.reason}</p>
                  ) : null}
                  {ecns.length > 0 ? (
                    <ul className="mt-2 space-y-1 border-t pt-2">
                      {ecns.map((ecn) => (
                        <li key={ecn.id} id={`ecn-${ecn.id}`} className="text-sm">
                          <span className="font-mono">{ecn.code}</span> {ecn.title}
                          <span className="ml-2 text-xs text-muted-foreground">
                            {ECN_STATUS_LABELS[ecn.status] ?? ecn.status}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
