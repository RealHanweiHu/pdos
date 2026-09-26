"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChangeDiscussionRuns } from "./change-discussion-runs";

import { DecisionResponsibility, DecisionResponsibilityLanding } from "./decision-responsibility";
import { DecisionIntakeSource, DecisionSourceRows, type HistoricalDecisionSource } from "@/components/projects/decision-intake-source";
import { Button } from "@/components/ui/button";

type Decision = {
  historical_source?: HistoricalDecisionSource | null;
  historical_origin_state?: Record<string, unknown> | null;
  source_finding_id?: string | null;
  id: string;
  decision_kind: string;
  title: string;
  outcome: string;
  context: string | null;
  options: string[];
  trade_offs: string | null;
  rationale: string | null;
  consequence: string | null;
  evidence_refs?: string[];
  owner_user_id?: string | null;
  approver_user_id?: string | null;
  execution_evidence?: ExecutionEvidence | null;
  follow_up_task_id?: string | null;
  gate_id?: string | null;
  follow_up_state: string;
  follow_up_note: string | null;
  decided_at: string;
};

type ExecutionEvidence = { audit_id: number; label: string; kind: string; target_id: string; executed_at: string };
type FormOptions = { members: { id: string; display_name: string }[]; tasks: { id: string; title: string }[]; gates: { id: string; name: string }[] };
const emptyDraft = { context: "", options: "", trade_offs: "", rationale: "", consequence: "", evidence_refs: "", owner: "", approver: "", follow_up_note: "", task: "", gate: "", pending: false };
const inputClass = "w-full rounded-md border bg-background p-2 text-sm";

type LoadState = "loading" | "ready" | "error";

type Props = {
  projectId: string;
  canEdit: boolean;
};

// Only these may be recorded by hand; gate and change decisions are written by
// their own flows so a hand-typed copy can never diverge from the real record.
const MANUAL_KINDS: ReadonlyArray<{ value: string; label: string }> = [
  { value: "technical_choice", label: "技术选型" },
  { value: "supplier_choice", label: "供应商选择" },
  { value: "process_decision", label: "流程决策" },
  { value: "rebaseline", label: "重定基线" },
  { value: "definition_release", label: "定义发布" },
  { value: "ccr_response", label: "客户变更答复" },
];

const KIND_LABELS: Record<string, string> = Object.fromEntries(
  MANUAL_KINDS.map((kind) => [kind.value, kind.label]),
);

const FOLLOW_UP_LABELS: Record<string, string> = {
  none: "无跟进",
  pending: "待跟进",
  completed: "已跟进",
};

async function readError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return body?.detail?.message ?? "操作失败";
  } catch {
    return "操作失败";
  }
}

/**
 * Decision log for the project.
 *
 * The tab previously showed a "coming in V2" placeholder while the backend had
 * served decisions since V1 — the record existed and nobody could read it.
 */
export function ProjectDecisionPanel({ projectId, canEdit }: Props) {
  const searchParams = useSearchParams();
  const uuidParam = (key:string) => {const v=searchParams.get(key);return v&&/^[0-9a-f-]{36}$/i.test(v)?v:undefined;};
  const discussionRunId=uuidParam("discussion_run_id"),discussionEcrId=uuidParam("discussion_ecr_id"),decisionId=uuidParam("decision_id");
  const [decisions, setDecisions] = useState<Decision[]>([]);
  useEffect(()=>{if(decisionId&&decisions.some(v=>v.id===decisionId))document.getElementById(`decision-${decisionId}`)?.scrollIntoView({block:"center"});},[decisionId,decisions]);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [ownerLock, setOwnerLock] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draftKind, setDraftKind] = useState(MANUAL_KINDS[0]!.value);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftOutcome, setDraftOutcome] = useState("");
  const [details, setDetails] = useState(emptyDraft);
  const [formOptions, setFormOptions] = useState<FormOptions>({ members: [], tasks: [], gates: [] });
  const [evidenceChoices, setEvidenceChoices] = useState<Record<string, ExecutionEvidence[]>>({});
  const [targetTasks, setTargetTasks] = useState<Record<string, string>>({});
  const [selectedEvidence, setSelectedEvidence] = useState<Record<string, string>>({});
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});

  const reload = useCallback(async () => {
    const response = await fetch(`/api/projects/${projectId}/decisions`, {
      cache: "no-store",
    });
    if (!response.ok) throw new Error(await readError(response));
    const body = await response.json();
    setDecisions(body.items ?? []);
  }, [projectId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const response = await fetch(`/api/projects/${projectId}/decisions`, {
          cache: "no-store",
        });
        if (!response.ok) throw new Error(await readError(response));
        const body = await response.json();
        if (cancelled) return;
        setDecisions(body.items ?? []);
        if (canEdit) {
        const optionsResponse = await fetch(`/api/projects/${projectId}/decisions/options`, { cache: "no-store" });
        if (!optionsResponse.ok) throw new Error(await readError(optionsResponse));
        const options = await optionsResponse.json();
        if (cancelled) return;
        if (!Array.isArray(options.members) || !Array.isArray(options.tasks) || !Array.isArray(options.gates)) throw new Error("决策办理选项格式错误，请刷新后重试");
        setFormOptions(options);
        }
        setState("ready");
      } catch (failure) {
        if (cancelled) return;
        setError(failure instanceof Error ? failure.message : "决策记录暂不可用");
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, canEdit]);

  useEffect(() => {
    if (state !== "ready") return;
    const target = window.location.hash.slice(1);
    if (decisions.some(decision => `decision-${decision.id}` === target)) {
      document.getElementById(target)?.scrollIntoView({ block: "center" });
    }
  }, [decisions, state]);

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
    return <p className="text-sm text-muted-foreground">正在加载决策记录…</p>;
  }

  if (state === "error") {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  return (
    <div className="space-y-6" data-testid="decision-panel">
      <DecisionResponsibilityLanding projectId={projectId}/>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      {canEdit ? (
        <section className="space-y-2 rounded-md border p-3">
          <h3 className="text-sm font-semibold">记录一条决策</h3>
          <div className="flex flex-wrap gap-2">
            <select
              aria-label="决策类型"
              className="h-9 rounded-md border px-2 text-sm"
              value={draftKind}
              onChange={(event) => setDraftKind(event.target.value)}
            >
              {MANUAL_KINDS.map((kind) => (
                <option key={kind.value} value={kind.value}>
                  {kind.label}
                </option>
              ))}
            </select>
            <input
              aria-label="决策标题"
              className="h-9 flex-1 rounded-md border px-2 text-sm"
              placeholder="决策标题"
              value={draftTitle}
              onChange={(event) => setDraftTitle(event.target.value)}
            />
          </div>
          <textarea
            aria-label="决策结论"
            className="min-h-16 w-full rounded-md border p-2 text-sm"
            placeholder="结论：决定了什么"
            value={draftOutcome}
            onChange={(event) => setDraftOutcome(event.target.value)}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            {(["context", "options", "trade_offs", "rationale", "consequence", "evidence_refs"] as const).map((key) => <label key={key} className="text-sm">
              {{ context: "背景", options: "考虑的选项（每行一项）", trade_offs: "方案权衡", rationale: "选择理由", consequence: "后果与影响", evidence_refs: "依据与证据引用（每行一条）" }[key]}
              <textarea className={inputClass} value={details[key]} onChange={(event) => setDetails({ ...details, [key]: event.target.value })} />
            </label>)}
            <label className="text-sm">批准人<select className={inputClass} value={details.approver} onChange={(event) => setDetails({ ...details, approver: event.target.value })}><option value="">选择批准人</option>{formOptions.members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
            <label className="text-sm">负责人<select className={inputClass} value={details.owner} onChange={(event) => setDetails({ ...details, owner: event.target.value })}><option value="">选择负责人</option>{formOptions.members.map((member) => <option key={member.id} value={member.id}>{member.display_name}</option>)}</select></label>
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={details.pending} onChange={(event) => setDetails({ ...details, pending: event.target.checked })} />需要后续执行</label>
          {details.pending && <div className="space-y-2">
            <label className="block text-sm">目标动作说明<textarea className={inputClass} value={details.follow_up_note} onChange={(event) => setDetails({ ...details, follow_up_note: event.target.value })} /></label>
            <label className="block text-sm">关联执行任务<select className={inputClass} value={details.task} onChange={(event) => setDetails({ ...details, task: event.target.value, gate: "" })}><option value="">选择未完成的项目任务</option>{formOptions.tasks.map((task) => <option key={task.id} value={task.id}>{task.title}</option>)}</select></label>
            <label className="block text-sm">或关联 Gate<select className={inputClass} value={details.gate} onChange={(event) => setDetails({ ...details, gate: event.target.value, task: "" })}><option value="">无关联 Gate</option>{formOptions.gates.map((gate) => <option key={gate.id} value={gate.id}>{gate.name}</option>)}</select></label>
            <p className="text-xs text-muted-foreground">执行完成后选择系统记录的凭据。重定基线、定义发布需由对应领域动作完成。</p>
          </div>}
          <Button
            size="sm"
            disabled={busy || !!ownerLock || !draftTitle.trim() || !draftOutcome.trim() || !details.approver || [details.context, details.options, details.trade_offs, details.rationale, details.consequence, details.evidence_refs].some((value) => !value.trim()) || (details.pending && (!details.owner || !details.follow_up_note.trim()))}
            onClick={() =>
              void act(async () => {
                const response = await fetch(`/api/projects/${projectId}/decisions`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    decision_kind: draftKind,
                    title: draftTitle.trim(),
                    outcome: draftOutcome.trim(),
                    context: details.context.trim(), options: details.options.split("\n").map((value) => value.trim()).filter(Boolean),
                    trade_offs: details.trade_offs.trim(), rationale: details.rationale.trim(), consequence: details.consequence.trim(),
                    evidence_refs: details.evidence_refs.split("\n").map((value) => value.trim()).filter(Boolean),
                    owner_user_id: details.owner || null, approver_user_id: details.approver,
                    follow_up_pending: details.pending, follow_up_note: details.pending ? details.follow_up_note.trim() : null,
                    follow_up_task_id: details.pending ? details.task || null : null,
                    gate_id: details.pending ? details.gate || null : null,
                  }),
                });
                if (!response.ok) throw new Error(await readError(response));
                setDraftTitle("");
                setDraftOutcome("");
                setDetails(emptyDraft);
              })
            }
          >
            记录决策
          </Button>
        </section>
      ) : null}

      {discussionRunId&&<ChangeDiscussionRuns key={discussionRunId} projectId={projectId} ecrId={discussionEcrId} source={{}} focusedRunId={discussionRunId} requestedOpen/>}
      <section className="space-y-3">
        <h3 className="text-sm font-semibold">决策日志</h3>
        {decisions.length === 0 ? (
          <p className="text-sm text-muted-foreground">尚无决策记录。</p>
        ) : (
          <ul className="space-y-3">
            {decisions.map((decision) => (
              <li id={`decision-${decision.id}`} key={decision.id} className="rounded-md border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{decision.title}</span>{decision.source_finding_id && <a className="ml-2 text-xs text-primary underline" href={`/ai-review?finding=${decision.source_finding_id}`}>查看会议建议与人审回执</a>}
                  <span className="text-xs text-muted-foreground">
                    {decision.historical_source ? "历史决策登记" : `${KIND_LABELS[decision.decision_kind] ?? decision.decision_kind} · ${FOLLOW_UP_LABELS[decision.follow_up_state] ?? decision.follow_up_state}`}
                  </span>
                </div>
                {decision.historical_source && <DecisionIntakeSource projectId={projectId} decisionId={decision.id} history={decision.historical_source} registeredAt={decision.decided_at} originState={decision.historical_origin_state} onChanged={reload}/>}
                {!decision.historical_source && <DecisionSourceRows projectId={projectId} decisionId={decision.id} onChanged={reload}/>}
                <p className="mt-1 text-sm">{decision.outcome}</p>
                <dl className="mt-2 space-y-1 text-sm">
                  {decision.context && <div><dt className="inline font-medium">背景：</dt><dd className="inline">{decision.context}</dd></div>}
                  {decision.options?.length > 0 && <div><dt className="font-medium">选项：</dt><dd><ul className="list-disc pl-5">{decision.options.map((option, index) => <li key={index}>{option}</li>)}</ul></dd></div>}
                  {decision.trade_offs && <div><dt className="inline font-medium">权衡：</dt><dd className="inline">{decision.trade_offs}</dd></div>}
                  {decision.consequence && <div><dt className="inline font-medium">后果：</dt><dd className="inline">{decision.consequence}</dd></div>}
                  {!!decision.evidence_refs?.length && <div><dt className="font-medium">证据：</dt><dd className="break-all">{decision.evidence_refs.join("；")}</dd></div>}
                  {decision.approver_user_id && <div><dt className="inline font-medium">批准人：</dt><dd className="inline">{formOptions.members.find((member) => member.id === decision.approver_user_id)?.display_name ?? "历史成员"}</dd></div>}
                </dl>
                {decision.execution_evidence && <p className="mt-2 text-sm">执行凭据：{decision.execution_evidence.label} · {new Date(decision.execution_evidence.executed_at).toLocaleString()}</p>}
                {decision.rationale ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    理由：{decision.rationale}
                  </p>
                ) : null}
                <DecisionResponsibility projectId={projectId} decisionId={decision.id} disabled={busy || !!ownerLock && ownerLock !== decision.id} onLock={value => setOwnerLock(value ? decision.id : null)} onChanged={reload}/>
                {decision.follow_up_note ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    跟进：{decision.follow_up_note}
                  </p>
                ) : null}
                {canEdit && decision.follow_up_state === "pending" ? (
                  <div className="mt-2 space-y-2">
                    {!decision.gate_id && ["technical_choice", "supplier_choice", "process_decision", "ccr_response"].includes(decision.decision_kind) && <div className="flex flex-wrap gap-2">
                      <select aria-label={`${decision.title} 目标任务`} className={inputClass} value={targetTasks[decision.id] ?? ""} onChange={(event) => setTargetTasks({ ...targetTasks, [decision.id]: event.target.value })}><option value="">{decision.follow_up_task_id ? "已有关联任务，可重新选择" : "关联一项待执行任务"}</option>{formOptions.tasks.map((task) => <option key={task.id} value={task.id}>{task.title}</option>)}</select>
                      <Button size="sm" variant="outline" disabled={busy || !!ownerLock || !targetTasks[decision.id]} onClick={() => void act(async () => {
                        const response = await fetch(`/api/projects/${projectId}/decisions/${decision.id}/execution-target`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ task_id: targetTasks[decision.id] }) });
                        if (!response.ok) throw new Error(await readError(response));
                        setEvidenceChoices((choices) => { const next = { ...choices }; delete next[decision.id]; return next; });
                        setSelectedEvidence((selected) => ({ ...selected, [decision.id]: "" }));
                      })}>关联执行任务</Button>
                    </div>}
                    <Button size="sm" variant="outline" disabled={busy || !!ownerLock} onClick={() => void act(async () => {
                      const response = await fetch(`/api/projects/${projectId}/decisions/${decision.id}/execution-evidence`, { cache: "no-store" });
                      if (!response.ok) throw new Error(await readError(response));
                      const body = await response.json();
                      setEvidenceChoices((choices) => ({ ...choices, [decision.id]: body.items ?? [] }));
                      setSelectedEvidence((selected) => ({ ...selected, [decision.id]: "" }));
                    })}>查找执行凭据</Button>
                    {evidenceChoices[decision.id]?.length === 0 && <p className="text-xs text-muted-foreground">尚无当前有效的关联目标执行凭据，请先完成对应动作并记录证据。</p>}
                    {!!evidenceChoices[decision.id]?.length && <select aria-label={`${decision.title} 执行凭据`} className={inputClass} value={selectedEvidence[decision.id] ?? ""} onChange={(event) => setSelectedEvidence({ ...selectedEvidence, [decision.id]: event.target.value })}><option value="">选择执行凭据</option>{evidenceChoices[decision.id]!.map((receipt) => <option key={receipt.audit_id} value={receipt.audit_id}>{receipt.label} · {new Date(receipt.executed_at).toLocaleString()}</option>)}</select>}
                    <input
                      aria-label={`${decision.title} 跟进说明`}
                      className="h-9 flex-1 rounded-md border px-2 text-sm"
                      placeholder="跟进说明"
                      value={noteDrafts[decision.id] ?? ""}
                      onChange={(event) =>
                        setNoteDrafts((drafts) => ({
                          ...drafts,
                          [decision.id]: event.target.value,
                        }))
                      }
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={busy || !!ownerLock || !selectedEvidence[decision.id] || !(noteDrafts[decision.id] ?? "").trim()}
                      onClick={() =>
                        void act(async () => {
                          const response = await fetch(
                            `/api/projects/${projectId}/decisions/${decision.id}/follow-up`,
                            {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify({
                                note: (noteDrafts[decision.id] ?? "").trim(),
                                execution_audit_id: Number(selectedEvidence[decision.id]),
                              }),
                            },
                          );
                          if (!response.ok) throw new Error(await readError(response));
                          setNoteDrafts((drafts) => ({ ...drafts, [decision.id]: "" }));
                        })
                      }
                    >
                      确认执行完成
                    </Button>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
