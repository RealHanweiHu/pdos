"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { answerKnowledgeCommand, knowledgeAnswerRoot, parseAnswerSeed, parseKnowledgeShare, restoreAnswerKnowledge, runAnswerKnowledge, type AnswerKnowledgePending, type AnswerKnowledgeSeed, type KnowledgeShare } from "@/lib/verified-knowledge";
import { knowledgeShareStorage, prepareKnowledgeShare, requestKnowledgeShare, restoreKnowledgeShare, type KnowledgeSharePending } from "@/lib/knowledge-share";
import type { ProjectWorkApi } from "@/lib/project-work";
import type { DomainCommand } from "@/lib/domain-candidate";
import { workRecord, workUuid } from "@/lib/project-work";

type Props = { api: ProjectWorkApi; categoryId?: string; principalId: string; runId: string; runRoot: string; disabled?: boolean };
export function AnswerKnowledgeActions(props: Props) { return <ScopedAnswerKnowledgeActions key={`${props.principalId}:${props.categoryId ?? "personal"}:${props.runId}`} {...props}/>; }
function ScopedAnswerKnowledgeActions(props: Props) {
  const { api, runId, runRoot, principalId, disabled } = props;
  const [categoryId, setCategoryId] = useState(props.categoryId ?? ""), [categories, setCategories] = useState<{ id: string; name: string }[]>([]);
  const [seed, setSeed] = useState<AnswerKnowledgeSeed | null>(null), [share, setShare] = useState<KnowledgeShare | null>(null), [error, setError] = useState(""), [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const [pending, setPending] = useState<KnowledgeSharePending | null>(null), [ready, setReady] = useState(false);
  const generation = useRef(0), sharing = useRef<KnowledgeSharePending | null>(null), locked = useRef(false);
  const storageKey = knowledgeShareStorage(principalId, runRoot, runId);
  useEffect(() => {
    const counter = generation, own = ++counter.current;
    void Promise.resolve().then(async () => {
      try {
        const raw = localStorage.getItem(storageKey);
        const restored = raw ? restoreKnowledgeShare(JSON.parse(raw), principalId, runRoot, runId) : null;
        if (raw && (!restored || props.categoryId && restored.category_id !== props.categoryId)) throw new Error("原补充请求记录不完整，请保留后核对，暂不能新建分享。");
        if (own !== generation.current) return;
        setReady(true);
        if (restored) {
          sharing.current = restored; setPending(restored); setCategoryId(restored.category_id);
          setNotice("已恢复原补充请求，正在只读核对提交结果。");
          void performShare(restored, true);
        }
      } catch (failure) { if (own === generation.current) setError((failure as Error).message); }
    });
    if (!props.categoryId) void api<unknown>("v1/categories").then(raw => {
      if (!Array.isArray(raw) || !raw.every(row => workRecord(row) && workUuid(row.id) && typeof row.name === "string")) throw new Error("目标品类暂未完整读取，请稍后重开本次回答。");
      if (own === generation.current) setCategories(raw);
    }).catch(failure => { if (own === generation.current) setError((failure as Error).message); });
    return () => { counter.current++; };
    // The recovered journal owns its exact category; target selection does not rerun recovery.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, props.categoryId, runId, runRoot, principalId, storageKey]);
  function selectCategory(value: string) { generation.current++; setCategoryId(value); setSeed(null); setShare(null); setError(""); setNotice(""); }
  async function open(kind: "category" | "rule") {
    if (busy || disabled || !categoryId) return; setBusy(true); setError(""); const own = generation.current;
    try { const raw = await api<unknown>(`${knowledgeAnswerRoot(categoryId)}/answer-draft`, { run_id: runId, kind }); if (own === generation.current) setSeed(parseAnswerSeed(raw, categoryId)); }
    catch (failure) { if (own === generation.current) setError((failure as Error).message); }
    finally { if (own === generation.current) setBusy(false); }
  }
  async function sharePreview(kind: "missing_material" | "shared_feedback") {
    if (busy || disabled || !categoryId || !ready || sharing.current) return; setBusy(true); setError(""); const own = generation.current;
    try {
      let feedback: string | null = null;
      if (kind === "shared_feedback") {
        const raw = await api<unknown>(`${runRoot}/${runId}/feedback`);
        if (!workRecord(raw) || raw.run_id !== runId || !Array.isArray(raw.items) || !raw.items.length || !workRecord(raw.items[0]) || !workUuid(raw.items[0].id)) throw new Error("请先记录本次回答反馈，再选择分享。");
        feedback = raw.items[0].id;
      }
      const raw = await api<unknown>(`${knowledgeAnswerRoot(categoryId)}/gaps/preview`, { run_id: runId, kind, feedback_id: feedback });
      if (own === generation.current) { setShare(parseKnowledgeShare(raw, categoryId, runId)); setNotice(""); }
    } catch (failure) { if (own === generation.current) setError((failure as Error).message); }
    finally { if (own === generation.current) setBusy(false); }
  }
  async function performShare(value: KnowledgeSharePending, reading: boolean) {
    if (locked.current || disabled) return; locked.current = true; setBusy(true); setError(""); const own = generation.current;
    try {
      if (!reading) localStorage.setItem(storageKey, JSON.stringify(value));
      sharing.current = value; setPending(value);
      await requestKnowledgeShare(api, value, reading);
      if (own === generation.current) {
        localStorage.removeItem(storageKey); sharing.current = null; setPending(null); setShare(null);
        setNotice(reading ? "已读回同一补充请求，未再次提交。" : "已提交给品类负责人。");
      }
    } catch (failure) { if (own === generation.current) {
      setError((failure as Error).message);
      if ([401, 403].includes((failure as { status?: number }).status ?? 0)) { setShare(null); setSeed(null); }
    } }
    finally { if (own === generation.current) { locked.current = false; setBusy(false); } }
  }
  function submitShare() {
    if (!share || busy || sharing.current || !ready) return;
    try { const value = prepareKnowledgeShare(share, principalId, runRoot, crypto.randomUUID()); void performShare(value, false); }
    catch (failure) { setError((failure as Error).message); }
  }
  return <section className="min-w-0 space-y-3 text-sm [overflow-wrap:anywhere]" aria-label="知识沉淀与补充">
    {!props.categoryId && <div className="space-y-2"><label className="block">目标品类<select aria-label="知识目标品类" className="mt-1 w-full rounded-lg border bg-background p-2" value={categoryId} disabled={busy || !!pending || disabled} onChange={event => selectCategory(event.target.value)}><option value="">请选择要整理到的品类</option>{categories.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><p className="text-muted-foreground">先明确选择目标品类。只能整理该品类的实际来源；跨品类回答请在对应品类重新查询后整理。</p>{!categories.length && <p>当前没有可读品类时，请联系品类负责人核对成员权限。</p>}</div>}
    <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={disabled || busy || !categoryId} onClick={() => void open("category")}>存为公司知识</Button><Button size="sm" variant="ghost" disabled={disabled || busy || !categoryId} onClick={() => void open("rule")}>存为经验候选</Button><Button size="sm" variant="ghost" disabled={disabled || busy || !categoryId || !ready || !!pending} onClick={() => void sharePreview("missing_material")}>请补充资料</Button><Button size="sm" variant="ghost" disabled={disabled || busy || !categoryId || !ready || !!pending} onClick={() => void sharePreview("shared_feedback")}>分享本次反馈</Button></div>
    {seed && <AnswerKnowledgeForm key={`${runId}:${categoryId}:${seed.operation}`} api={api} seed={seed} principalId={principalId} target={runId} onClose={() => setSeed(null)}/>}
    {share && !pending && <div className="space-y-3 rounded-lg border p-4"><h3 className="font-medium">提交给 {share.recipient.category_name} · {share.recipient.name}</h3><p className="whitespace-pre-wrap">{share.question}</p>{share.answer !== null && <details><summary>本次分享的回答</summary><p className="whitespace-pre-wrap">{share.answer}</p></details>}<p className="text-muted-foreground">范围：{[share.recipient.category_name, share.search_scope.product_name, share.search_scope.project_name, share.search_scope.proposal_title].filter(Boolean).join(" · ")}</p><div className="flex gap-2"><Button size="sm" disabled={busy || !ready} onClick={submitShare}>提交补充请求</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setShare(null)}>取消</Button></div></div>}
    {pending && <div className="space-y-2 rounded-lg border p-3" aria-label="原补充请求核对"><p>原提交结果待核对。刷新只读取原结果，重试仍使用同一原请求。</p><details><summary>原请求标识</summary><p>{pending.request.request_key}</p></details><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy || disabled} onClick={() => void performShare(pending, true)}>读取原请求结果</Button><Button size="sm" variant="ghost" disabled={busy || disabled} onClick={() => void performShare(pending, false)}>重试原补充请求</Button></div></div>}
    {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
  </section>;
}

export function AnswerKnowledgeForm({ api, seed, principalId, target, onClose, onSaved }: { api: ProjectWorkApi; seed: AnswerKnowledgeSeed; principalId: string; target: string; onClose: () => void; onSaved?: () => void }) {
  const initialReview = seed.payload.knowledge_review as { responsible_id: string; applicability_scope: string; review_due_at: string } | undefined;
  const [title, setTitle] = useState(String((seed.payload.content as Record<string, unknown> | undefined)?.title ?? seed.payload.title ?? "")), [answer, setAnswer] = useState(seed.operation === "knowledge.candidate.create" ? String(seed.payload.lesson) : seed.answer);
  const [responsible, setResponsible] = useState(initialReview?.responsible_id ?? seed.default_responsible_id), [scope, setScope] = useState(initialReview?.applicability_scope ?? ""), [date, setDate] = useState(initialReview?.review_due_at.slice(0, 10) ?? ""), [deidentified, setDeidentified] = useState(false);
  const [saved, setSaved] = useState(false);
  const [pending, setPending] = useState<AnswerKnowledgePending | null>(null), [preview, setPreview] = useState<DomainCommand | null>(null), [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false), [ready, setReady] = useState(false), [denied, setDenied] = useState(false);
  const epoch = useRef(0), locked = useRef(false), key = `pdos.answer-knowledge.v1:${principalId}:${seed.command_scope.category_id}:${target}:${seed.operation}`;
  useEffect(() => { const counter = epoch, own = ++counter.current; void Promise.resolve().then(() => { if (own !== epoch.current) return; try { const raw = sessionStorage.getItem(key), saved = raw ? restoreAnswerKnowledge(JSON.parse(raw), seed.command_scope.category_id) : null; if (raw && !saved) throw new Error("原保存请求不完整，已保留供核对。");
      if (saved && saved.command.operation === seed.operation && saved.command.product_id === seed.command_scope.product_id) {
        const payload = saved.command.payload, review = payload.knowledge_review as { responsible_id: string; applicability_scope: string; review_due_at: string };
        setPending(saved); setTitle(String((payload.content as Record<string, unknown> | undefined)?.title ?? payload.title ?? "")); setAnswer(String((payload.content as Record<string, unknown> | undefined)?.answer ?? payload.lesson ?? ""));
        if (review) { setResponsible(review.responsible_id); setScope(review.applicability_scope); setDate(review.review_due_at.slice(0, 10)); }
        setNotice("已恢复原保存请求。"); } setReady(true); } catch { setError("原请求存储暂不可用，请恢复后重试。"); } }); return () => { counter.current++; }; }, [key, seed.command_scope.category_id, seed.command_scope.product_id, seed.operation]);
  function persist(value: AnswerKnowledgePending) { sessionStorage.setItem(key, JSON.stringify(value)); setPending(value); }
  async function execute(value: AnswerKnowledgePending) {
    if (locked.current || denied) return; locked.current = true; setBusy(true); setError(""); const own = epoch.current;
    try {
      persist(value);
      const result = await runAnswerKnowledge(api, value, principalId, step => { if (own === epoch.current) persist(step); });
      if (own !== epoch.current || !result) return;
      if (result.stage === "preview") { setPreview(result.prepared.command as DomainCommand); setNotice("请核对去标识内容。"); }
      else { sessionStorage.removeItem(key); setPending(null); setPreview(null); setSaved(true); setNotice("知识已保存。可从知识页重新打开。"); onSaved?.(); }
    } catch (failure) { if (own === epoch.current) { setError((failure as Error).message); if ([401, 403].includes((failure as { status?: number }).status ?? 0)) { sessionStorage.removeItem(key); setPending(null); setPreview(null); setDenied(true); } } }
    finally { if (own === epoch.current) { locked.current = false; setBusy(false); } }
  }
  function save() { try { void execute(answerKnowledgeCommand(seed, { title, answer, review: { responsible_id: responsible, applicability_scope: scope, review_due_at: date ? `${date}T23:59:59Z` : "" }, deidentified })); } catch (failure) { setError((failure as Error).message); } }
  const editable = ready && !busy && !pending && !denied && !saved;
  return <div className="space-y-3 rounded-lg border p-4" aria-label="整理知识"><h3 className="font-medium">{seed.operation === "knowledge.candidate.create" ? "经验候选" : "整理核实答案"} · AI 草稿</h3>{!denied && <><label className="block">标题<input className="mt-1 w-full rounded-lg border bg-background p-2" value={title} disabled={!editable} onChange={event => setTitle(event.target.value)}/></label><p>{seed.question}</p><label className="block">内容<textarea className="mt-1 min-h-36 w-full rounded-lg border bg-background p-2" value={answer} disabled={!editable} onChange={event => setAnswer(event.target.value)}/></label><div className="grid gap-3 sm:grid-cols-2"><label>负责人<select className="mt-1 w-full rounded-lg border bg-background p-2" value={responsible} disabled={!editable} onChange={event => setResponsible(event.target.value)}>{seed.people.map(person => <option key={person.id} value={person.id}>{person.name}</option>)}</select></label><label>复核日期<input type="date" className="mt-1 w-full rounded-lg border bg-background p-2" value={date} disabled={!editable} onChange={event => setDate(event.target.value)}/></label></div><label className="block">适用范围<textarea className="mt-1 w-full rounded-lg border bg-background p-2" value={scope} disabled={!editable} onChange={event => setScope(event.target.value)}/></label><p className="text-muted-foreground">{seed.basis_count} 项已核来源</p>{seed.operation === "category.knowledge.promote" && <label className="flex gap-2"><input type="checkbox" checked={deidentified} disabled={!editable} onChange={event => setDeidentified(event.target.checked)}/>已完成客户与私有资料的去标识整理</label>}{preview && <div><p className="mb-2 whitespace-pre-wrap">{JSON.stringify(preview.payload.content, null, 2)}</p><Button size="sm" disabled={busy} onClick={() => void execute({ stage: "execute", command: preview })}>确认沉淀</Button></div>}<div className="flex flex-wrap gap-2">{!preview && !saved && <Button size="sm" disabled={!ready || busy || denied} onClick={() => pending ? void execute(pending) : save()}>{pending ? "核对原保存请求" : "保存知识"}</Button>}<Button size="sm" variant="ghost" disabled={busy} onClick={onClose}>关闭</Button></div></>}{notice && <p role="status">{notice}</p>}{saved && <Link className="text-primary underline underline-offset-4" href="/?area=knowledge">打开知识</Link>}{error && <p role="alert">{error}</p>}</div>;
}
