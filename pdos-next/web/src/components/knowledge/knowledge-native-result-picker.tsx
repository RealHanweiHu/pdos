"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import type { KnowledgeScope } from "@/lib/knowledge-experience";
import {
  knowledgeNativeAvailable, knowledgeNativeConfigurationKey, knowledgeNativeContextKey,
  knowledgeNativeSourceKey, parseKnowledgeNativeContext, selectKnowledgeNative,
  type KnowledgeNativeContext, type KnowledgeNativeKeys, type KnowledgeNativeSelection,
} from "@/lib/knowledge-experience-native";

export type KnowledgeNativeResultPickerProps = {
  context: KnowledgeNativeContext | null;
  scope: KnowledgeScope;
  /** False while the candidate is readonly, authority is unresolved, or saving. */
  editable: boolean;
  onSelect: (selection: KnowledgeNativeSelection) => void;
};

const empty = (): KnowledgeNativeKeys => ({ results: [], sources: [], configurations: [] });
const groups = { field: "现场反馈", change: "变更记录", other: "其他实际结果" } as const;
const visibilityNames = { private: "私有", category: "品类可读", audience: "指定受众" } as const;
const unavailable = (reason: string | null) => reason ?? "当前不可选，请重新核对实际依据。";

export function KnowledgeNativeResultPicker({ context, scope, editable, onSelect }: KnowledgeNativeResultPickerProps) {
  let current: KnowledgeNativeContext | null = null, problem = "";
  try { if (context) current = parseKnowledgeNativeContext(context, scope); } catch (error) { problem = error instanceof Error ? error.message : "实际目录未核实，请重新读取。"; }
  const basis = current ? knowledgeNativeContextKey(current) : null;
  const [state, setState] = useState<{ basis: string | null; keys: KnowledgeNativeKeys; error: string }>({ basis: null, keys: empty(), error: "" });
  const live = useRef<{ basis: string | null; editable: boolean; onSelect: typeof onSelect } | null>(null);
  useEffect(() => { live.current = { basis, editable, onSelect }; return () => { live.current = null; }; }, [basis, editable, onSelect]);
  const keys = state.basis === basis ? state.keys : empty();
  const error = state.basis === basis ? state.error : "";
  function active() { return !!current && basis !== null && live.current?.basis === basis && live.current.editable === true; }
  function toggle(group: keyof KnowledgeNativeKeys, value: string, checked: boolean) {
    if (!active()) return;
    setState(previous => {
      const selected = previous.basis === basis ? previous.keys : empty();
      return { basis, error: "", keys: { ...selected, [group]: checked ? [...new Set([...selected[group], value])] : selected[group].filter(key => key !== value) } };
    });
  }
  function choose() {
    if (!active() || !current) return;
    try { live.current?.onSelect(selectKnowledgeNative(current, scope, keys)); }
    catch (failure) { setState({ basis, keys, error: failure instanceof Error ? failure.message : "所选材料尚未核实，请重新选择。" }); }
  }
  if (!current) return <section aria-label="选择实际结果与原件" className="space-y-3 rounded-lg border border-border p-4"><h3 className="font-semibold">选择实际结果与原件</h3><p role={problem ? "alert" : "status"}>{problem || "实际目录尚未取得，暂不能带入旧材料。"}</p></section>;
  return <section aria-label="选择实际结果与原件" className="space-y-4 rounded-lg border border-border p-4 [overflow-wrap:anywhere]">
    <header><h3 className="font-semibold">选择实际结果与原件</h3><p className="text-sm text-muted-foreground">从本次可读目录明确选择；也可以只选原件记录候选。选择不会保存候选或发布规则。</p></header>
    <p className="text-sm text-muted-foreground">目录读取于 {current.as_of}。刷新、切换范围或翻页后须重新选择。</p>
    {!editable && <p role="status" className="text-sm">当前表单只读或办理权限尚未核实，不能带入材料。</p>}
    <fieldset disabled={!editable} className="min-w-0 space-y-4">
      <section className="space-y-2" aria-label="可选实际结果"><h4 className="font-medium">实际结果回执（可不选）</h4>
        {!current.result_options.length && <p className="text-sm text-muted-foreground">本页没有可选结果回执；可继续选择实际原件。</p>}
        {current.result_options.map(row => <label key={row.receipt_id} className="block space-y-1 rounded-lg border border-border p-3"><span className="flex items-start gap-2"><input type="checkbox" aria-label={`结果：${row.title}`} checked={keys.results.includes(row.receipt_id)} disabled={!editable || !knowledgeNativeAvailable(row)} onChange={event => toggle("results", row.receipt_id, event.target.checked)}/><span>{row.title} · {groups[row.family]} · {visibilityNames[row.visibility]}</span></span><span className="block text-sm text-muted-foreground">{row.operation} · 固定 v{row.subject.revision} · {row.recorded_at}</span>{row.reason !== null || !row.selectable ? <span className="block text-sm">{unavailable(row.reason)}</span> : null}</label>)}
      </section>
      <section className="space-y-2" aria-label="可选实际原件"><h4 className="font-medium">实际原件（至少选一条）</h4>
        {!current.source_options.length && <p className="text-sm text-muted-foreground">本页没有实际原件，请由目录入口重新读取或翻页。</p>}
        {current.source_options.map(row => { const key = knowledgeNativeSourceKey(row.ref); return <label key={key} className="block space-y-1 rounded-lg border border-border p-3"><span className="flex items-start gap-2"><input type="checkbox" aria-label={`原件：${row.title}`} checked={keys.sources.includes(key)} disabled={!editable || !knowledgeNativeAvailable(row)} onChange={event => toggle("sources", key, event.target.checked)}/><span>{row.title} · v{row.ref.revision} · {visibilityNames[row.visibility]}</span></span><span className="block whitespace-pre-wrap text-sm">{row.excerpt}</span>{row.reason !== null || !row.selectable ? <span className="block text-sm">{unavailable(row.reason)}</span> : null}</label>; })}
      </section>
      <section className="space-y-2" aria-label="可选关联配置"><h4 className="font-medium">关联配置（可不选）</h4><p className="text-sm text-muted-foreground">只保留明确选择的配置引用，适用性仍须分别核对。</p>
        {!current.configuration_options.length && <p className="text-sm text-muted-foreground">本页没有可选关联配置。</p>}
        {current.configuration_options.map(row => { const key = knowledgeNativeConfigurationKey(row.ref); return <label key={key} className="block space-y-1 rounded-lg border border-border p-3"><span className="flex items-start gap-2"><input type="checkbox" aria-label={`配置：${row.name}`} checked={keys.configurations.includes(key)} disabled={!editable || !knowledgeNativeAvailable(row)} onChange={event => toggle("configurations", key, event.target.checked)}/><span>{row.name} · {row.ref.kind === "engineering_configuration" ? "工程配置" : "制造配置"} · v{row.ref.revision}</span></span>{row.reason !== null || !row.selectable ? <span className="block text-sm">{unavailable(row.reason)}</span> : null}</label>; })}
      </section>
      {error && <p role="alert">{error}</p>}
      <Button type="button" disabled={!editable || !keys.sources.length} onClick={choose}>带入所选实际材料</Button>
    </fieldset>
  </section>;
}
