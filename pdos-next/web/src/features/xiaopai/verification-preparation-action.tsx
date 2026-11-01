"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { readProjectBuilds, type ProjectBuildRecord } from "@/lib/project-build-summary";
import { verificationAnswerSources, verificationStart, type VerificationAnswerRun, type VerificationBuildRef } from "@/lib/verification-action";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import type { SourceRead } from "@/lib/project-plan-view";

type Props = {
  api: WorkspaceTransport; categoryId: string; run: VerificationAnswerRun; disabled?: boolean;
  additionalSources?: SourceRead[]; initialBuildId?: string;
  onStart: (request: ReturnType<typeof verificationStart>) => void;
  onUnavailable?: () => void;
};
export function VerificationPreparationAction(props: Props) {
  const sources = verificationAnswerSources(props.run);
  if (!sources.length) return null;
  return <Action key={props.run.run_id} {...props} sources={sources}/>;
}
function Action({ api, categoryId, run, disabled, additionalSources = [], initialBuildId, onStart, onUnavailable, sources }: Props & { sources: ReturnType<typeof verificationAnswerSources> }) {
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [builds, setBuilds] = useState<ProjectBuildRecord[]>([]), [selected, setSelected] = useState("");
  const [citations, setCitations] = useState(sources.map(source => source.citation_id));
  const alive = useRef(true), generation = useRef(0);
  useEffect(() => { const counter = generation; alive.current = true; return () => { alive.current = false; counter.current++; }; }, []);
  const build = builds.find(value => value.id === selected);
  async function load() {
    if (busy || disabled) return;
    setOpen(true); setBusy(true); setError(""); setBuilds([]); setSelected("");
    const own = ++generation.current;
    try {
      const value = await readProjectBuilds(api, { categoryId, productId: run.product_id!, projectId: run.project_id! });
      if (!alive.current || own !== generation.current) return;
      setBuilds(value.items);
      if (initialBuildId && value.items.some(row => row.id === initialBuildId)) setSelected(initialBuildId);
      else if (value.items.length === 1) setSelected(value.items[0].id);
    } catch (failure) {
      if (!alive.current || own !== generation.current) return;
      setError(failure instanceof Error ? failure.message : "本项目Build暂不可读。");
      if ([401, 403].includes((failure as { status?: number }).status ?? 0)) { setOpen(false); onUnavailable?.(); }
    } finally { if (alive.current && own === generation.current) setBusy(false); }
  }
  function start() {
    if (disabled || busy || !build || !citations.length) return;
    const selection: VerificationBuildRef = {
      id: build.id, revision: build.revision, product_id: run.product_id!, project_id: run.project_id!,
      engineering_configuration: { id: build.engineering_configuration.id, revision: build.engineering_configuration.revision },
      manufacturing_configuration: { id: build.manufacturing_configuration.id, revision: build.manufacturing_configuration.revision },
    };
    try { onStart(verificationStart(run, selection, citations, additionalSources, crypto.randomUUID(), build.name)); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "准备请求暂不可用。"); }
  }
  if (!open) return <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void load()}>准备复验请求</Button>;
  return <section aria-label="准备复验请求" className="min-w-0 space-y-3 rounded-lg border border-border p-3 text-sm [overflow-wrap:anywhere]">
    <header className="flex flex-wrap items-center justify-between gap-2"><h4 className="font-medium">准备复验请求</h4><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setOpen(false)}>收起</Button></header>
    {error && <p role="alert">{error}</p>}
    {busy ? <p role="status" className="text-muted-foreground">正在读取本项目Build…</p> : <>
      <label className="block space-y-1">本次复验Build<select className="w-full min-w-0" aria-label="本次复验Build" value={selected} disabled={disabled} onChange={event => setSelected(event.target.value)}><option value="">请选择本项目Build</option>{builds.map(row => <option key={row.id} value={row.id}>{row.name} · v{row.revision}</option>)}</select></label>
      {build && <p className="text-muted-foreground">{build.name} · v{build.revision}<br/>工程配置：{build.engineering_configuration.name} · v{build.engineering_configuration.revision}<br/>制造配置：{build.manufacturing_configuration.name} · v{build.manufacturing_configuration.revision}</p>}
      {!builds.length && <p className="text-muted-foreground">本项目暂未读到可选Build。</p>}
      <fieldset disabled={disabled} className="space-y-1"><legend className="mb-1 font-medium">参考案例</legend>{sources.map(source => <label key={source.citation_id} className="flex min-w-0 items-start gap-2"><input type="checkbox" checked={citations.includes(source.citation_id)} onChange={event => setCitations(old => event.target.checked ? [...old, source.citation_id] : old.filter(cid => cid !== source.citation_id))}/><span>{source.title} · v{source.source_revision}</span></label>)}</fieldset>
      <div className="flex flex-wrap gap-2"><Button type="button" size="sm" variant="outline" disabled={disabled || !build || !citations.length} onClick={start}>开始准备</Button><Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => void load()}>刷新Build</Button></div>
    </>}
  </section>;
}
