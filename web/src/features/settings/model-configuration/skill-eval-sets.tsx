"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { parseEvalCases, type EvalSet } from "@/features/settings/lib/skill-qualification";
import { proofClockCurrent } from "@/lib/proof-clock";
import type { WorkspaceTransport } from "@/lib/workspace-api";

const fieldClass = "w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm";
const example = JSON.stringify([{ case_id: "N-01", case_type: "N", category_ref: "auto-tire-inflator", material_kind: "synthetic", inputs: ["录制的研究快照 v1"], must_cover: ["标注未知的工况"], must_not: [], keep_unknown: [], traps: [], key_points: [] }], null, 2);
type Preview = { command: Record<string, unknown>; expires_at: string | null; review: { version: number; title: string; case_count: number; case_types: Record<string, number>; material_kinds: Record<string, number>; categories: string[]; cases_sha256: string; effect: string } };

// Registered evaluation sets per tenant × skill package (P110): frozen versions the
// user's own reviews can cite. Registering grants no qualification.
export function SkillEvalSets({ api, skill, categoryId, categoryRevision, sets, canEdit, onRegistered }: { api: WorkspaceTransport; skill: string; categoryId: string; categoryRevision: number; sets: EvalSet[]; canEdit: boolean; onRegistered: () => void }) {
  const [title, setTitle] = useState(""), [raw, setRaw] = useState(""), [signed, setSigned] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const focus = useRef<HTMLElement>(null);
  useEffect(() => { if (preview) focus.current?.focus(); }, [preview]);
  async function act(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }
  return <section aria-label="资格评测集" className="space-y-3 rounded-lg border border-border p-3 text-sm">
    <h3 className="font-medium">资格评测集</h3>
    <p className="text-muted-foreground">按“租户 × 技能包”登记固定版本，审阅时引用其中的案例，并按当前模型版本统计已审阅的覆盖。登记不授予任何资格；评测集定版与参考要点由你本人负责，小Pai 不能写入。</p>
    {error && <p role="alert" className="break-words text-destructive">{error}</p>}{notice && <p role="status" className="break-all">{notice}</p>}
    {!sets.length && <p className="text-muted-foreground">尚未登记评测集。</p>}
    {sets.length > 0 && <ul className="space-y-2">{sets.map(set => <li key={set.id} className="space-y-1 rounded-lg bg-muted/40 p-2"><p className="font-medium">第 {set.version} 版 · {set.title}</p><p className="break-all text-xs text-muted-foreground">{set.case_count} 个案例 · sha256 {set.cases_sha256.slice(0, 12)}… · {set.registered_by_name} · {new Date(set.created_at).toLocaleString("zh-CN")}</p><p>当前技能与模型已审阅 {set.reviewed_case_ids.length} / {set.case_count} 个案例</p></li>)}</ul>}
    {canEdit && <details className="space-y-3"><summary className="cursor-pointer font-medium">登记新版本评测集</summary>
      <fieldset disabled={busy || !!preview} className="mt-3 space-y-3">
        <label className="block space-y-1"><span>评测集名称</span><input className={fieldClass} maxLength={200} value={title} onChange={event => setTitle(event.target.value)} /></label>
        <label className="block space-y-1"><span>案例清单（JSON 数组，字段按评测规则 §5.2）</span><textarea className={`${fieldClass} font-mono text-xs`} rows={8} value={raw} placeholder={example} onChange={event => { setRaw(event.target.value); setSigned(false); }} /></label>
        <label className="flex items-start gap-2"><input type="checkbox" className="mt-1" checked={signed} onChange={event => setSigned(event.target.checked)} /><span>参考要点由我本人或我指定的人员编写并签名。</span></label>
        <Button disabled={!title.trim() || !raw.trim() || !signed} onClick={() => void act(async () => {
          const cases = parseEvalCases(raw);
          const result = await api<Preview>("v1/commands/preview", { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), category_id: categoryId, product_id: null, operation: "ai.skill.eval_set.register", expected_revision: categoryRevision, source_read_set: [], payload: { skill_key: skill, title, cases, reference_points_signed: true } });
          setPreview(result); setNotice("");
        })}>预览登记评测集</Button>
      </fieldset>
    </details>}
    {preview && <section ref={focus} tabIndex={-1} aria-label="确认登记评测集" className="space-y-2 rounded-lg border border-primary/40 p-3">
      <p className="font-medium">确认登记第 {preview.review.version} 版 · {preview.review.title}</p>
      <p>{preview.review.case_count} 个案例 · 类型 {Object.entries(preview.review.case_types).map(([type, count]) => `${type} ${count}`).join("、")} · 品类 {preview.review.categories.join("、")}</p>
      <p className="break-all text-xs text-muted-foreground">sha256 {preview.review.cases_sha256}</p>
      <p>{preview.review.effect}</p>
      <div className="flex flex-wrap gap-2"><Button disabled={busy || !proofClockCurrent("T1", preview.expires_at)} onClick={() => void act(async () => {
        const receipt = await api<{ id: string }>("v1/commands", preview.command);
        setPreview(null); setTitle(""); setRaw(""); setSigned(false);
        setNotice(`评测集已登记 · 回执 ${receipt.id}`); onRegistered();
      })}>确认登记</Button><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>返回</Button></div>
    </section>}
  </section>;
}
