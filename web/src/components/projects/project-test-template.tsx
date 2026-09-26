"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { fetchTestTemplates, saveTestTemplate } from "./project-npi-api";
import type { TestCoverage } from "./project-npi-types";

export function TestCoverageView({ coverage }: { coverage?: TestCoverage }) {
  if (!coverage || coverage.status === "unconfigured") {
    return <p className="mt-2 text-sm text-muted-foreground">尚未选择测试模板，无法判断必测覆盖。</p>;
  }
  return <div className="mt-2 space-y-2 text-sm">
    {coverage.scope_status === "changed" && <p className="text-destructive">{coverage.scope_message}</p>}
    <p>{coverage.template_name} · v{coverage.version}</p>
    <p>必测 {coverage.required} 项 · 有结果证据 {coverage.covered} 项 · 待补 {coverage.missing} 项 · 不适用 {coverage.not_applicable} 项</p>
    <p className="text-muted-foreground">通过 {coverage.passed} 项 · 失败 {coverage.failed} 项。按已确认且附证据的测试项计数；不代表样机数量或 Gate 验收通过。</p>
    <details>
      <summary className="cursor-pointer">查看缺项与不适用理由</summary>
      <ul className="mt-2 space-y-1">
        {coverage.items.filter((item) => item.state !== "passed").map((item) => <li key={item.key}>
          {item.title}：{item.state === "not_applicable" ? `不适用；${item.reason}` : item.state === "failed" ? "测试失败" : "待补已确认的结果与证据"}
        </li>)}
      </ul>
    </details>
  </div>;
}

export function ProjectTestTemplate({ projectId, planId, onSaved }: {
  projectId: string; planId?: string; onSaved: () => Promise<void>;
}) {
  const [options, setOptions] = useState<Awaited<ReturnType<typeof fetchTestTemplates>> | null>(null);
  const [selected, setSelected] = useState("");
  const [stageId, setStageId] = useState("");
  const [title, setTitle] = useState("");
  const [sampleSize, setSampleSize] = useState(1);
  const [exclusions, setExclusions] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const template = options?.templates.find((item) => `${item.id}:${item.version}` === selected);

  async function open() {
    setBusy(true); setError(null);
    try { setOptions(await fetchTestTemplates(projectId)); }
    catch { setError("测试模板暂不可用，请重试。"); }
    finally { setBusy(false); }
  }

  if (!options) return <div className="space-y-2">
    <Button variant="outline" size="sm" disabled={busy} onClick={() => void open()}>
      {planId ? "选择测试模板" : "从模板创建测试计划"}
    </Button>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>;

  const required = template?.items.filter((item) => item.required && !(item.key in exclusions)).length ?? 0;
  return <form className="space-y-3 rounded-md border p-3" onSubmit={async (event) => {
    event.preventDefault();
    const stage = options.stages.find((item) => item.id === stageId);
    if (!template || (!planId && !stage)) return;
    setBusy(true); setError(null);
    try {
      await saveTestTemplate(projectId, {
        template_id: template.id, version: template.version, product_type: template.product_type,
        exclusions: Object.entries(exclusions).map(([key, reason]) => ({ key, reason: reason.trim() })),
      }, planId ? { planId } : {
        stage_id: stage!.id, phase: stage!.code, title: title.trim(), sample_size: sampleSize,
      });
      await onSaved(); setOptions(null);
    } catch (failure) { setError(failure instanceof Error ? failure.message : "保存失败，请重试。"); }
    finally { setBusy(false); }
  }}>
    {options.product_scope_message && <p className="text-sm text-muted-foreground">{options.product_scope_message}</p>}
    <label className="block text-sm">产品类型与模板版本
      <select required value={selected} className="mt-1 block w-full rounded-md border bg-background p-2"
        onChange={(event) => { setSelected(event.target.value); setExclusions(options.templates.find((item) => `${item.id}:${item.version}` === event.target.value)?.locked_exclusions ?? {}); }}>
        <option value="">请选择</option>
        {options.templates.map((item) => <option key={`${item.id}:${item.version}`} value={`${item.id}:${item.version}`}>
          {item.product_type} · {item.name} v{item.version}
        </option>)}
      </select>
    </label>
    {!planId && <div className="flex flex-wrap gap-3">
      <label className="text-sm">计划名称<input required maxLength={512} value={title}
        onChange={(event) => setTitle(event.target.value)} className="mt-1 block rounded-md border bg-background p-2" /></label>
      <label className="text-sm">测试阶段<select required value={stageId} onChange={(event) => setStageId(event.target.value)}
        className="mt-1 block rounded-md border bg-background p-2"><option value="">请选择</option>
        {options.stages.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
      </select></label>
      <label className="text-sm">计划样机数量<input required type="number" min={1} value={sampleSize}
        onChange={(event) => setSampleSize(Number(event.target.value))} className="mt-1 block w-24 rounded-md border bg-background p-2" /></label>
    </div>}
    {template && <>
      <p className="text-sm">必测 {required} 项 · 不适用 {Object.keys(exclusions).length} 项。创建后全部为待测，不继承参考报告的结果。</p>
      <details><summary className="cursor-pointer text-sm">查看标准并设置项目不适用项</summary>
        <ul className="mt-2 space-y-3">{template.items.map((item) => <li key={item.key} className="border-t pt-2 text-sm">
          <p className="font-medium">{item.title}{item.required ? " · 必测" : " · 选测"}</p>
          <p className="whitespace-pre-wrap text-muted-foreground">{item.acceptance_criteria}</p>
          <label className="flex items-center gap-2"><input type="checkbox" checked={item.key in exclusions} disabled={!!template.locked_exclusions?.[item.key] || template.required_enabled?.includes(item.key)}
            onChange={(event) => setExclusions((previous) => {
              const next = { ...previous };
              if (event.target.checked) next[item.key] = ""; else delete next[item.key];
              return next;
            })} />{item.title}不适用于本项目</label>
          {item.key in exclusions && <label className="block">不适用理由（{item.title}）
            <input required readOnly={!!template.locked_exclusions?.[item.key]} maxLength={2000} value={exclusions[item.key]} className="mt-1 w-full rounded-md border bg-background p-2"
              onChange={(event) => setExclusions({ ...exclusions, [item.key]: event.target.value })} />
          </label>}
        </li>)}</ul>
      </details>
    </>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex gap-2">
      <Button type="submit" size="sm" disabled={busy || !template || required === 0 || Object.values(exclusions).some((reason) => !reason.trim())}>
        确认模板与项目差异
      </Button>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setOptions(null)}>取消</Button>
    </div>
  </form>;
}
