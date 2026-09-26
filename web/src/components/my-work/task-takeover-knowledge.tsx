"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";

export type KnowledgeReference = { push_id: string; content_sha256: string; note: string };
export type KnowledgeChoice = KnowledgeReference & { title: string; href: string; applicability?: string };

export function TaskTakeoverKnowledge({ choices, values, onChange, disabled, hasMore }: {
  choices: KnowledgeChoice[];
  values: KnowledgeReference[];
  onChange: (values: KnowledgeReference[]) => void;
  disabled: boolean;
  hasMore: boolean;
}) {
  return <section className="space-y-2 rounded-md border p-3" aria-label="关联已采用经验">
    <p className="font-medium">关联已采用经验（选填，最多10条）</p>
    <p className="text-muted-foreground">先在接手资料的“相关经验”中记录采用，再刷新交接依据选择。填写给接收人的适用说明，提交时固定原采用版本；接收人按自己的资料权限核对原文。</p>
    {hasMore ? <p>仅展示最近50次采用记录中当前有效的经验，更早记录未在此列表展示。</p> : null}
    {!choices.length ? <p className="text-muted-foreground">暂无本人在此任务中已采用且当前有效的经验。</p> : null}
    {choices.map(item => <div className="flex items-start gap-2" key={item.push_id}>
      <div className="min-w-0 flex-1"><Link className="text-primary underline" href={item.href}>{item.title}</Link><p>{item.applicability}</p></div>
      <Button type="button" size="sm" variant="outline" disabled={disabled || values.length >= 10 || values.some(value => value.push_id === item.push_id)} onClick={() => onChange([...values, { push_id: item.push_id, content_sha256: item.content_sha256, note: "" }])}>关联此经验</Button>
    </div>)}
    {values.map((item, index) => {
      const choice = choices.find(value => value.push_id === item.push_id && value.content_sha256 === item.content_sha256);
      return <div className="space-y-2 rounded-md border p-2" key={item.push_id}>
        <p>{choice?.title ?? "原关联经验当前不可选，请移除并重新核对"}</p>
        <p className="break-all text-muted-foreground">固定版本：{item.content_sha256}</p>
        <label className="block">对本任务的适用说明／需要接续的做法<textarea required maxLength={4000} disabled={disabled} className="mt-1 w-full rounded-md border bg-background p-2" value={item.note} onChange={e => onChange(values.map((value, i) => i === index ? { ...value, note: e.target.value } : value))}/></label>
        <Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => onChange(values.filter((_, i) => i !== index))}>移除此经验</Button>
      </div>;
    })}
  </section>;
}
