"use client";

import { useEffect, useRef, useState } from "react";
import { FirmwarePackageTasks } from "./firmware-package-tasks";
import { ProfessionalChangeRoute } from "./professional-change-route";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import { SampleConfigurationSnapshot } from "./sample-configuration-snapshot";

type Row = Record<string, unknown>;
type Kind = "issue" | "configuration" | "test_run" | "build";
type Source = { kind: Kind; id: string; snapshot: Row; digest: string };
type Selection = Source & { use: "context" | "reproduction" | "regression"; basis: string };
type Component = { kind: "software" | "app"; name: string; version: string; git_reference: string; change_notes: string };
const kinds: Record<Kind, string> = { issue: "原问题", configuration: "样机历史配置", test_run: "逐次测试记录", build: "试制批次" };
const fields = { git_reference: "固件 Git 提交或标签及仓库说明", change_notes: "版本变更说明", observations: "观察到的事实与日志原文定位", reproduction_steps: "复现步骤、条件与实际表现", hypotheses: "调查假设及其依据（尚未证实）", verification_plan: "验证清单与完成判据", unknowns: "未知影响与待补资料", coordination: "协同专业、接收方与待办说明", reason: "本次登记或修订依据" };
type Fields = Record<keyof typeof fields, string>;
const blank = (): Fields => Object.fromEntries(Object.keys(fields).map(k => [k, ""])) as Fields;
const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const text = (v: unknown) => v === null || v === undefined || v === "" ? "未知" : String(v);
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const states: Record<string, string> = { passed: "通过", failed: "失败", aborted: "终止", in_progress: "进行中", planned: "计划中", open: "待处理", closed: "已关闭", resolved: "待验证", completed: "已完成" };
const obj = (v: unknown): Row => isRecord(v) ? v : {};
function label(s: Source) {
  const v = s.snapshot;
  if (s.kind === "configuration") return `${text(obj(v.sample).serial_number)} · 配置 v${text(v.revision_number)} · FW ${text(obj(v.snapshot).fw_version)}`;
  if (s.kind === "test_run") return `${text(obj(v.case).title)} · 第 ${text(v.run_number)} 次 · ${states[text(v.status)] ?? text(v.status)}`;
  return `${text(v.title ?? v.code)} · ${states[text(v.status)] ?? text(v.status)}`;
}
function sourceFrom(v: Row): Source | null {
  if (!(String(v.kind) in kinds) || typeof v.id !== "string" || !isRecord(v.snapshot) || typeof v.digest !== "string") return null;
  return { kind: v.kind as Kind, id: v.id, snapshot: v.snapshot, digest: v.digest };
}
function SourceView({ source, projectId, version }: { source: Source; projectId: string; version: string }) {
  const v = source.snapshot, configuration = obj(v.configuration), configVersion = obj(configuration.snapshot).fw_version;
  return <div className="space-y-2 text-xs">
    <p className="font-medium">{kinds[source.kind]}：{label(source)}</p>
    {source.kind === "issue" && <><p className="whitespace-pre-wrap">{text(v.description)}</p><p>已登记根因：{text(v.root_cause)}</p><a className="text-primary underline" href={`/projects?project=${projectId}&tab=issues&entity_id=${source.id}`}>查看原问题与当前处置</a></>}
    {source.kind === "configuration" && <SampleConfigurationSnapshot revision={v} referenceOnly />}
    {source.kind === "test_run" && <><p>记录状态：{v.draft_state === "confirmed" ? "已确认" : "草稿"} · 实际日期：{v.execution_time_precision === "unknown" ? "未知" : text(v.executed_at)} · 原始证据：{v.evidence_document_id ? "已关联" : "缺少"}</p><p>当次固件：{text(configVersion)} · {configVersion == null ? "尚不能确认与本版本的关系" : configVersion === version ? "版本号与本工作包一致，仍需核对回归范围" : "与本工作包固件不同，不能据此认定本版本回归通过"}</p><p className="whitespace-pre-wrap">测试说明：{text(v.result_notes)}</p><SampleConfigurationSnapshot revision={v.configuration} /><a className="mr-3 text-primary underline" href={`/projects?project=${projectId}&tab=quality&test_case_id=${text(v.test_case_id)}&test_run_id=${source.id}`}>查看原测试记录</a>{typeof v.evidence_document_id === "string" && <a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${v.evidence_document_id}`}>查看原报告证据</a>}</>}
    {source.kind === "build" && <p>{text(v.phase).toUpperCase()} · 计划 {text(v.planned_quantity)} 台 · 已完成 {text(v.completed_quantity)} 台</p>}
  </div>;
}
function PackageView({ record, projectId }: { record: Row; projectId: string }) {
  const snapshot = obj(record.snapshot);
  return <div className="space-y-3 text-xs">
    <p>登记人：{text(record.created_by_name ?? record.created_by_user_id)} · {text(record.created_at)}</p>
    <dl className="grid gap-3 sm:grid-cols-2">{Object.entries(fields).map(([key, title]) => <div key={key}><dt className="font-medium">{title}</dt><dd className="mt-1 whitespace-pre-wrap break-words">{text(snapshot[key])}</dd></div>)}</dl>
    {rows(snapshot.components).map((component, i) => <div className="rounded-md border p-2" key={i}><p>{component.kind === "app" ? "App" : "软件"} · {text(component.name)} · {text(component.version)}</p><p>{text(component.git_reference)}</p><p className="whitespace-pre-wrap">{text(component.change_notes)}</p></div>)}
    {rows(snapshot.sources).map(v => { const source = sourceFrom({ ...v, digest: v.expected_digest }); return source && <div key={`${source.kind}:${source.id}`} className="space-y-2 rounded-md border p-2"><SourceView source={source} projectId={projectId} version={text(snapshot.firmware_version)} /><p>用途：{{ context: "背景", reproduction: "复现依据", regression: "回归证据" }[String(v.use)] ?? text(v.use)} · {text(v.basis)}</p></div>; })}
  </div>;
}
export function ProjectFirmwareWorkPackages({ projectId, canEdit, canRecordResults = canEdit }: { projectId: string; canEdit: boolean; canRecordResults?: boolean }) {
  const panel = useRef<HTMLDetailsElement>(null);
  const [targetRecord, setTargetRecord] = useState<Row | null>(null);
  const [history, setHistory] = useState<Row[] | null>(null), [cursor, setCursor] = useState<string | null>(null);
  const [version, setVersion] = useState(""), [checkedVersion, setCheckedVersion] = useState<string | null>(null), [current, setCurrent] = useState<Row | null>(null);
  const [values, setValues] = useState<Fields>(blank), [intent, setIntent] = useState("investigation"), [components, setComponents] = useState<Component[]>([]);
  const [selected, setSelected] = useState<Selection[]>([]), [kind, setKind] = useState<Kind>("issue"), [options, setOptions] = useState<Source[]>([]), [sourceCursor, setSourceCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null), [dirty, setDirty] = useState(false);
  const [changed, setChanged] = useState(false);
  const attempt = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/npi/firmware-work-packages`;
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("firmware_package_id");
    if (!id || !/^[0-9a-f-]{36}$/i.test(id)) return;
    let active = true;
    void fetch(`${base}/${id}/tasks`, { cache: "no-store" }).then(async response => {
      const value: unknown = await response.json();
      if (!response.ok || !isRecord(value) || !isRecord(value.package)) throw new Error("原固件工作包暂不可用，请刷新后重试");
      if (!active) return;
      const record = value.package;
      setTargetRecord({ ...record, firmware_version: obj(record.snapshot).firmware_version });
      if (panel.current) panel.current.open = true;
    }).catch((e: unknown) => { if (active) { setError(e instanceof Error ? e.message : "原工作包读取失败"); if (panel.current) panel.current.open = true; } });
    return () => { active = false; };
  }, [base]);
  useEffect(() => { if (targetRecord) document.getElementById(`firmware-package-${String(targetRecord.id)}`)?.scrollIntoView({ block: "center" }); }, [targetRecord]);
  async function request(path: string, body?: unknown): Promise<Row> {
    const response = await fetch(`${base}${path}`, body === undefined ? { cache: "no-store" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const value: unknown = await response.json();
    if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "资料办理未完成，请核对输入或稍后重试");
    if (!isRecord(value)) throw new Error("返回资料不完整");
    return value;
  }
  async function act(fn: () => Promise<void>) { setBusy(true); setError(null); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "办理未完成"); } finally { setBusy(false); } }
  async function loadHistory(more = false) { const result = await request(more && cursor ? `?before_id=${cursor}` : ""); setHistory(previous => more ? [...(previous ?? []), ...rows(result.items)] : rows(result.items)); setCursor(typeof result.next_cursor === "string" ? result.next_cursor : null); }
  async function loadCurrent() {
    const next = version.trim(); if (!next) return;
    const result = await request(`/current?version=${encodeURIComponent(next)}`), p = isRecord(result.package) ? result.package : null, snapshot = obj(p?.snapshot);
    setCurrent(p); setCheckedVersion(next); setVersion(next); setValues(Object.fromEntries(Object.keys(fields).map(k => [k, k === "reason" ? "" : typeof snapshot[k] === "string" ? snapshot[k] : ""])) as Fields); setIntent(snapshot.intent === "release_preparation" ? "release_preparation" : "investigation");
    setComponents(rows(snapshot.components).map(c => ({ kind: c.kind === "app" ? "app" : "software", name: text(c.name), version: text(c.version), git_reference: text(c.git_reference), change_notes: text(c.change_notes) })));
    const latest = rows(result.sources); setChanged(latest.some(s => s.changed === true));
    setSelected(rows(snapshot.sources).flatMap(s => { const parsed = sourceFrom({ ...s, digest: s.expected_digest }); return parsed ? [{ ...parsed, use: s.use === "regression" ? "regression" as const : s.use === "reproduction" ? "reproduction" as const : "context" as const, basis: typeof s.basis === "string" ? s.basis : "" }] : []; }));
    setOptions([]); setSourceCursor(null); setDirty(false); setNotice(null); attempt.current = null;
  }
  async function loadSources(more = false) { const result = await request(`/sources?kind=${kind}${more && sourceCursor ? `&after_id=${sourceCursor}` : ""}`); const data = rows(result.items).flatMap(v => { const s = sourceFrom(v); return s ? [s] : []; }); setOptions(prior => more ? [...prior, ...data] : data); setSourceCursor(typeof result.next_cursor === "string" ? result.next_cursor : null); }
  function edit() { setDirty(true); setNotice(null); }
  const ready = checkedVersion === version.trim() && Object.values(values).every(v => v.trim()) && selected.every(s => s.basis.trim()) && (intent !== "investigation" || (selected.some(s => s.kind === "issue") && selected.some(s => s.kind === "configuration")));
  return <details ref={panel} className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !history && !busy) void act(() => loadHistory()); }}>
    <summary className="cursor-pointer text-sm font-semibold">固件与软件 · 问题调查及版本交付资料</summary>
    <div className="mt-3 space-y-4 text-sm">
      <p className="text-xs text-muted-foreground">按实际固件版本整理问题、当时配置、复现日志和回归记录，可附关联软件及 App 版本。保存资料后继续专业验证和交付办理；代码与发布记录由原 Git 流程管理。</p>
      {canEdit && <>
        <div className="flex flex-wrap items-end gap-2"><label className="min-w-0 flex-1 text-xs">实际固件版本<input className={input} maxLength={64} value={version} disabled={busy || dirty} onChange={e => { setVersion(e.target.value); setCheckedVersion(null); }} /></label><Button type="button" variant="outline" size="sm" disabled={busy || dirty || !version.trim()} onClick={() => void act(loadCurrent)}>读取最新资料</Button>{dirty && <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void act(loadCurrent)}>放弃本次编辑并重新读取</Button>}</div>
        {checkedVersion === version.trim() && <form className="space-y-3" onSubmit={e => { e.preventDefault(); void act(async () => {
          const payload = { expected_package_id: current?.id ?? null, firmware_version: version.trim(), intent, ...Object.fromEntries(Object.entries(values).map(([k, v]) => [k, v.trim()])), components, sources: selected.map(s => ({ kind: s.kind, id: s.id, expected_digest: s.digest, use: s.use, basis: s.basis.trim() })) };
          const signature = JSON.stringify(payload); if (attempt.current?.signature !== signature) attempt.current = { signature, id: crypto.randomUUID() };
          const result = await request("", { ...payload, request_id: attempt.current.id }); setCurrent(result); setDirty(false); attempt.current = null; setValues(v => ({ ...v, reason: "" })); setNotice(`资料版本 ${text(result.revision_number)} 已保存。`); await loadHistory();
        }); }}>
          <fieldset disabled={busy} className="space-y-3">
            <label className="block text-xs">工作目的<select className={input} value={intent} onChange={e => { setIntent(e.target.value); edit(); }}><option value="investigation">问题复现与调查</option><option value="release_preparation">版本交付准备</option></select></label>
            <div className="grid gap-3 sm:grid-cols-2">{Object.entries(fields).map(([key, title]) => <label className="block text-xs" key={key}>{title}<textarea className={input} required value={values[key as keyof Fields]} maxLength={key === "git_reference" ? 512 : key === "reason" ? 2000 : key === "coordination" ? 4000 : 10000} placeholder={key === "unknowns" || key === "hypotheses" ? "未明确的内容请说明；无假设或无待补项时写明依据" : undefined} onChange={e => { setValues({ ...values, [key]: e.target.value }); edit(); }} /></label>)}</div>
            <details className="rounded-md border p-2"><summary className="cursor-pointer text-xs">关联软件 / App 版本（{components.length}）</summary><div className="mt-2 space-y-2">{components.map((c, i) => <div key={i} className="grid gap-2 rounded-md border p-2 sm:grid-cols-2"><label className="text-xs">类型<select className={input} value={c.kind} onChange={e => { setComponents(components.map((v, n) => n === i ? { ...v, kind: e.target.value as Component["kind"] } : v)); edit(); }}><option value="software">软件</option><option value="app">App</option></select></label>{([['name', '组件名称', 128], ['version', '实际版本', 64], ['git_reference', 'Git 提交或标签及仓库说明', 512], ['change_notes', '变更说明', 4000]] as const).map(([key, title, max]) => <label key={key} className="text-xs">{title}<input className={input} required maxLength={max} value={c[key]} onChange={e => { setComponents(components.map((v, n) => n === i ? { ...v, [key]: e.target.value } : v)); edit(); }} /></label>)}<Button type="button" variant="outline" size="sm" onClick={() => { setComponents(components.filter((_, n) => i !== n)); edit(); }}>移除此组件</Button></div>)}<Button type="button" variant="outline" size="sm" disabled={components.length >= 20} onClick={() => { setComponents([...components, { kind: "app", name: "", version: "", git_reference: "", change_notes: "" }]); edit(); }}>添加关联软件版本</Button></div></details>
            {changed && <p className="text-xs text-primary">原工作包的部分来源已变化。请通过下方来源选择重新核对并替换引用，保存时会再次检查当前版本。</p>}
            <div className="rounded-md border p-2"><p className="font-medium">选择真实来源</p><div className="my-2 flex flex-wrap gap-2"><select aria-label="来源类型" className={input} value={kind} onChange={e => { setKind(e.target.value as Kind); setOptions([]); setSourceCursor(null); }}>{Object.entries(kinds).map(([k, title]) => <option key={k} value={k}>{title}</option>)}</select><Button type="button" size="sm" variant="outline" onClick={() => void act(() => loadSources())}>读取本项目来源</Button>{sourceCursor && <Button type="button" variant="outline" size="sm" onClick={() => void act(() => loadSources(true))}>更多来源</Button>}</div><div className="max-h-96 space-y-2 overflow-y-auto">{options.map(s => <details className="rounded-md border p-2" key={`${s.kind}:${s.id}`}><summary className="cursor-pointer text-xs">{label(s)}</summary><div className="mt-2 space-y-2"><SourceView source={s} projectId={projectId} version={version.trim()} /><Button type="button" size="sm" variant="outline" disabled={selected.length >= 100 && !selected.some(v => v.kind === s.kind && v.id === s.id)} onClick={() => { const old = selected.find(v => v.kind === s.kind && v.id === s.id); const next: Selection = { ...s, use: old?.use ?? "context", basis: old?.basis ?? "" }; setSelected(old ? selected.map(v => v.kind === s.kind && v.id === s.id ? next : v) : [...selected, next]); edit(); }}>{selected.some(v => v.kind === s.kind && v.id === s.id) ? "按当前原记录重新核对引用" : "引用此来源"}</Button></div></details>)}</div></div>
            <div className="space-y-2">{selected.map((s, i) => <div className="space-y-2 rounded-md border p-2" key={`${s.kind}:${s.id}`}><SourceView source={s} projectId={projectId} version={version.trim()} /><label className="block text-xs">引用用途<select className={input} value={s.use} onChange={e => { setSelected(selected.map((v, n) => n === i ? { ...v, use: e.target.value as Selection["use"] } : v)); edit(); }}><option value="context">背景 / 范围</option><option value="reproduction">复现依据</option>{s.kind === "test_run" && <option value="regression">回归证据</option>}</select></label><label className="block text-xs">与本版本或问题的关系及原文定位<textarea className={input} required maxLength={2000} value={s.basis} onChange={e => { setSelected(selected.map((v, n) => n === i ? { ...v, basis: e.target.value } : v)); edit(); }} /></label><Button type="button" variant="outline" size="sm" onClick={() => { setSelected(selected.filter((_, n) => n !== i)); edit(); }}>移除此引用</Button></div>)}</div>
            <p className="text-xs text-muted-foreground">问题调查须关联原问题及当时配置。回归引用保留真实结果、证据及配置差异；待测、失败、缺证据或版本不同仍须处理。保存资料后可在下方办理实际验证与协同任务。</p>
            <Button type="submit" size="sm" disabled={!ready}>保存新的资料版本</Button>
          </fieldset>
        </form>}
      </>}
      {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
      <div className="space-y-2"><div className="flex flex-wrap gap-2"><h4 className="font-medium">已保存的版本资料</h4><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => loadHistory())}>刷新历史</Button></div>{history?.length === 0 && <p className="text-xs text-muted-foreground">尚未保存工作包资料。</p>}{[...(targetRecord ? [targetRecord] : []), ...(history ?? []).filter(record => record.id !== targetRecord?.id)].map(record => <details id={`firmware-package-${text(record.id)}`} open={record.id === targetRecord?.id || undefined} key={text(record.id)} className="rounded-md border p-2"><summary className="cursor-pointer text-xs">FW {text(record.firmware_version)} · 资料 v{text(record.revision_number)} · {obj(record.snapshot).intent === "investigation" ? "问题调查" : "交付准备"}</summary><div className="mt-3"><PackageView record={record} projectId={projectId} /><ProfessionalChangeRoute projectId={projectId} sourceId={text(record.id)} kind="firmware_package" canEdit={canEdit} /><FirmwarePackageTasks projectId={projectId} packageId={text(record.id)} canEdit={canEdit} canRecordResults={canRecordResults} /></div></details>)}{cursor && <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void act(() => loadHistory(true))}>更早的资料</Button>}</div>
    </div>
  </details>;
}
