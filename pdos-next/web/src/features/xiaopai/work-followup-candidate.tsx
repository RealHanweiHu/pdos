"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { blankWorkLocal, newWorkCommand, readProjectWork, restoreWorkLocal, runProjectWorkRequest, workInputs, workPreviewCurrent, workReceipt, workRoot, workSame, workStorageKey, type WorkInputs, type WorkLocal, type WorkPending, type WorkPrepared, type WorkScope, type WorkCommand } from "@/lib/project-work";
import { projectWorkspaceHref } from "@/lib/project-workspace-navigation";
import { workFollowupCandidate } from "@/lib/work-followup";
import type { DomainCandidate } from "@/lib/domain-candidate";
import type { WorkspaceTransport } from "@/lib/workspace-api";

type Props = { api: WorkspaceTransport; categoryId: string; principalId: string; candidate: DomainCandidate; disabled?: boolean; onRefresh: () => void; onUnavailable?: () => void };
export function WorkFollowupCandidate(props: Props) {
  const command = props.candidate.command;
  if (!command || typeof command.product_id !== "string" || typeof command.payload.project_id !== "string") return <p>任务候选已不可用，请刷新核对。</p>;
  const scope = { categoryId: props.categoryId, principalId: props.principalId, productId: command.product_id, projectId: command.payload.project_id };
  if (!workFollowupCandidate(props.candidate, scope)) return <p role="alert">任务候选与当前项目无法核对。</p>;
  return <Candidate key={props.candidate.event_id} {...props} candidate={props.candidate} scope={scope}/>;
}
function Candidate({ api, candidate, scope, disabled, onRefresh, onUnavailable }: Props & { scope: WorkScope; candidate: DomainCandidate & { command: WorkCommand } }) {
  const storageKey = `${workStorageKey(scope)}:answer:${candidate.event_id}`;
  const [local, setLocal] = useState<WorkLocal>(() => blankWorkLocal(scope)), [ready, setReady] = useState(false);
  const [inputs, setInputs] = useState<WorkInputs | null>(null), [prepared, setPrepared] = useState<WorkPrepared | null>(null);
  const [denied, setDenied] = useState(false);
  const [people, setPeople] = useState<{ assignee: string; recipient: string } | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [, setClock] = useState(0);
  const current = useRef(local), alive = useRef(true), lock = useRef(false);
  const command = candidate.command!;
  const task = candidate.task;
  const valid = workFollowupCandidate(candidate, scope);
  useEffect(() => {
    alive.current = true;
    void Promise.resolve().then(() => {
      if (!alive.current) return;
      try {
      const saved = restoreWorkLocal(JSON.parse(localStorage.getItem(storageKey) ?? "null"), scope);
      if (saved) {
        const pending = saved.pending?.command;
        if (pending && (pending.operation === "work.task.create" && !workSame(pending, command)
          || pending.operation === "work.task.assign" && pending.payload.task && (pending.payload.task as { id?: string }).id !== candidate.task?.id)) throw new Error("本机原请求与该任务候选不一致。");
        current.current = saved; setLocal(saved);
      }
      setReady(true);
      } catch { setError("本机原请求暂不可核对，已停止提交。请恢复本机存储后刷新。"); }
    });
    return () => { alive.current = false; };
    // The event is immutable; a refresh only rereads native status and receipts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storageKey]);
  useEffect(() => {
    if (!prepared) return;
    const timer = setInterval(() => setClock(value => value + 1), 1000);
    return () => clearInterval(timer);
  }, [prepared]);
  function persist(value: WorkLocal) {
    localStorage.setItem(storageKey, JSON.stringify(value)); current.current = value; setLocal(value);
  }
  function failure(value: unknown) {
    setError(value instanceof Error ? value.message : "请求结果尚未核实，请核对原请求。");
    if ([401, 403].includes((value as { status?: number }).status ?? 0)) {
      setInputs(null); setPrepared(null); setDenied(true);
      try { localStorage.removeItem(storageKey); } catch { /* The denied view remains hidden. */ }
      onUnavailable?.();
    }
  }
  async function review() {
    if (lock.current || disabled || !ready || current.current.pending || candidate.state !== "pending" || !valid) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const value = workInputs(await api(`${workRoot(scope)}/project-work/inputs`, command), command, scope);
      if (!value) throw new Error("原任务材料与服务器核对结果不一致。");
      if (alive.current) setInputs(value);
    } catch (value) { if (alive.current) failure(value); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function perform(pending: WorkPending) {
    if (lock.current || disabled || !ready || !valid) return;
    lock.current = true; setBusy(true); setError("");
    try {
      persist({ ...current.current, operation: pending.command.operation, pending, receipt: null, completed: null });
      const value = await runProjectWorkRequest(api, pending, scope, next => persist({ ...current.current, pending: next }), () => alive.current);
      if (!value || !alive.current) return;
      if (value.stage === "preview") { setPrepared(value.prepared); persist({ ...current.current, pending: null }); }
      else { persist({ ...current.current, pending: null, receipt: value.receipt, completed: value.command }); setPrepared(null); setInputs(null); onRefresh(); }
    } catch (value) { if (alive.current) failure(value); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }
  async function assignment() {
    if (!candidate.assignment || !task || lock.current || disabled || current.current.pending) return;
    lock.current = true; setBusy(true); setError("");
    let pending: WorkPending | undefined;
    try {
      const reading = await readProjectWork(api, scope);
      const actual = reading.tasks.find(value => value.id === task.id);
      if (!actual || reading.project.owner_id !== scope.principalId) throw new Error("请由当前项目负责人核对真实任务后分派。");
      const assignee = reading.members.find(value => value.id === candidate.assignment!.assignee_id && value.can_write);
      const recipient = reading.members.find(value => value.id === candidate.assignment!.recipient_id && value.can_write);
      if (!assignee || !recipient) throw new Error("本次所选办理人的当前身份已变化，请重新核对。");
      setPeople({ assignee: assignee.name, recipient: recipient.name });
      const payload = { project_id: scope.projectId, task: { id: actual.id, revision: actual.revision }, sources: actual.sources, reason: "按本次明确选择的人员分派资料跟进任务", ...candidate.assignment };
      pending = { stage: "inputs", command: newWorkCommand(scope, reading.product_revision, "work.task.assign", payload, actual) };
    } catch (value) { if (alive.current) failure(value); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
    if (pending && alive.current) await perform(pending);
  }
  const savedCreate = candidate.state === "adopted" && candidate.receipt && task;
  const outcomeRows = Array.isArray(command.payload.outcomes) ? command.payload.outcomes as { key: string; text: string; required: boolean }[] : [];
  const safeToAct = ready && !disabled && !busy && valid && !local.pending;
  if (denied) return <p role="alert">{error || "任务材料已不可读，请刷新核对。"}</p>;
  return <article className="space-y-3 rounded-lg border p-3 text-sm" aria-label="资料跟进任务候选">
    <h4 className="font-medium">{savedCreate ? task.title : String(command.payload.title)}</h4>
    {error && <p role="alert">{error}</p>}
    {savedCreate ? <><p>任务已创建 · 当前状态：{({ proposed: "待分派", assigned: "已分派，待本人承接", accepted: "已承接", in_progress: "进行中", submitted: "已提交", completed: "已完成" } as Record<string, string>)[task.state] ?? "请打开核对"}</p><Link className="underline" href={projectWorkspaceHref(scope.categoryId, scope.productId, scope.projectId, "tasks")}>打开项目任务</Link>{candidate.assignment && task.state === "proposed" && <Button size="sm" variant="outline" disabled={!safeToAct || !!prepared} onClick={() => void assignment()}>核对分派</Button>}</> : <><p className="text-muted-foreground">小Pai起草 · 尚未创建</p><p>目标：{String(command.payload.goal)}</p><ul>{outcomeRows.map(value => <li key={value.key}>{value.text}{value.required ? "（必需）" : ""}</li>)}</ul><p>原件引用：{Array.isArray(command.payload.sources) ? command.payload.sources.length : 0} 条。日期待本人另行明确，不作出日期承诺。</p>{!inputs ? <Button size="sm" variant="outline" disabled={!safeToAct || candidate.state !== "pending"} onClick={() => void review()}>核对任务材料</Button> : <><p>材料已由原项目工作入口核对。确认后创建当前固定任务。</p><Button size="sm" disabled={!safeToAct || candidate.state !== "pending"} onClick={() => { if (workFollowupCandidate(candidate, scope)) void perform({ stage: "execute", command: candidate.command }); }}>确认创建任务</Button></>}</>}
    {prepared && <section className="space-y-2 rounded border p-2" aria-label="确认任务分派"><p>分派由本人确认，执行人仍须自行承接。</p>{people && <p>执行人：{people.assignee}；成果接收人：{people.recipient}</p>}<p>{workPreviewCurrent(prepared) ? "本次分派确认材料有效。" : "确认已过期，请重新核对分派。"}</p><Button disabled={!safeToAct || !workPreviewCurrent(prepared)} onClick={() => void perform({ stage: "execute", command: prepared.command })}>确认分派</Button></section>}
    {local.pending && <div className="space-y-2"><p>原请求结果待核实。刷新不会再次提交。</p><Button variant="outline" disabled={!ready || disabled || busy} onClick={() => void perform(local.pending!)}>核对原请求</Button></div>}
    {local.receipt && local.completed && workReceipt(local.receipt, local.completed) && <p role="status">{local.receipt.operation === "work.task.assign" ? "已取得本次分派回执。" : "已取得本次创建回执。"}</p>}
  </article>;
}
