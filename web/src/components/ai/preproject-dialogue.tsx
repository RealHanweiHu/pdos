"use client";

import { Dialog } from "radix-ui";
import { XIcon } from "@phosphor-icons/react";
import { useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { CandidateSources, ProposalCandidatePreview, type CandidateCitation } from "./preproject-candidate";
import type { ProposalDocument } from "@/components/product-work/proposal-types";

export type PreprojectAssessment = {
  goal: "category" | "proposal"; stage: "clarify" | "ready"; candidate_digest: string;
  questions: { id: string; question: string; options: string[]; recommendation: string }[];
  category: {code:string;title:string;user_groups:string[];regions:string[];use_scenarios:string[];research_questions:string[];parameters:{key:string;label:string;unit:string;conditions:string;direction:string;verification_method?:string;acceptance_criterion?:string}[];notes:{kind:string;title:string;body:string;state:string;citation_ids?:string[]}[]} | null;
  proposal: {title:string;entry_kind:string;document:ProposalDocument} | null;
};

export function PreprojectDialogue({assessment,citations=[],autoOpen=true,disabled,onAnswer,onConfirm}: {assessment:PreprojectAssessment;citations?:CandidateCitation[];autoOpen?:boolean;disabled:boolean;onAnswer:(body:string)=>void;onConfirm:()=>Promise<void>}) {
  const [open,setOpen]=useState(autoOpen),[answers,setAnswers]=useState<Record<string,string>>({}),[shared,setShared]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState("");
  const descriptionId=useId();
  const clarify=assessment.stage==="clarify",category=assessment.category,proposal=assessment.proposal;
  const title=clarify?"先确认这几个关键问题":category?"品类与研究资料候选":"立项提案编辑稿";
  return <div className="mt-3">
    <Button size="sm" variant="outline" disabled={disabled} onClick={()=>setOpen(true)}>{clarify?"回答关键问题":"查看并保存候选"}</Button>
    <Dialog.Root open={open} onOpenChange={value=>{if(!saving)setOpen(value);}}><Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-black/50"/><Dialog.Content aria-describedby={descriptionId} className="fixed left-1/2 top-1/2 z-[60] flex max-h-[90dvh] w-[calc(100%_-_2rem)] max-w-2xl -translate-x-1/2 -translate-y-1/2 flex-col rounded-lg border bg-background p-5 shadow-xl sm:p-6">
      <div className="flex items-center justify-between gap-3"><Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title><Dialog.Close asChild><Button variant="ghost" size="icon" disabled={saving} aria-label="关闭问题弹窗"><XIcon/></Button></Dialog.Close></div>
      <Dialog.Description id={descriptionId} className="mt-2 text-sm leading-6 text-muted-foreground">{clarify?"只确认会改变方向的问题。查资料的工作交给小Pai，其余未知可以继续保留。":"核对方向与已有依据后保存。规格条件、法规适用性与专业结论仍需后续确认。"}</Dialog.Description>
      <form className="mt-5 min-h-0 space-y-5 overflow-y-auto pr-1" onSubmit={async e=>{e.preventDefault();setError("");if(clarify){const body=assessment.questions.map(q=>`${q.id}：${answers[q.id]?.trim()}`).join("\n");onAnswer(body);setOpen(false);return;}setSaving(true);try{await onConfirm();setOpen(false);}catch(e){setError(e instanceof Error?e.message:"保存未确认，可以重试原候选");}finally{setSaving(false);}}}>
        {clarify?assessment.questions.map(q=><fieldset key={q.id} disabled={disabled||saving} className="space-y-3"><legend className="mb-2 text-sm font-medium">{q.question}</legend>{q.recommendation&&<p className="text-xs leading-5 text-muted-foreground">建议：{q.recommendation}</p>}{q.options.map(option=><label key={option} className="flex items-start gap-2 rounded-lg border p-3 text-sm"><input type="radio" name={q.id} className="mt-1" checked={answers[q.id]===option} onChange={()=>setAnswers(v=>({...v,[q.id]:option}))}/>{option}</label>)}<label className="block space-y-1 text-sm"><span>你的回答</span><input required maxLength={380} value={answers[q.id]??""} onChange={e=>setAnswers(v=>({...v,[q.id]:e.target.value}))} className="w-full rounded-lg border bg-background p-2" placeholder="可选上面的建议，也可直接说明"/></label></fieldset>):<>
          <h3 className="font-semibold">{category?.title??proposal?.title}</h3>
          {category&&<><dl className="grid gap-3 text-sm sm:grid-cols-2">{[["编号",category.code],["用户",category.user_groups.join("、")],["地区",category.regions.join("、")],["场景",category.use_scenarios.join("、")]].map(([label,value])=><div key={label}><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1">{value}</dd></div>)}</dl><section className="space-y-2"><h4 className="text-sm font-medium">规格字典候选 · {category.parameters.length}项</h4>{category.parameters.map(p=><article key={p.key} className="rounded-lg border p-3 text-sm">{p.label} · {p.unit}<span className="mt-1 block text-xs text-muted-foreground">{p.conditions} · {{higher:"越大越好",lower:"越小越好",target:"接近目标",neutral:"不排序"}[p.direction]}<br/>测试方法：{p.verification_method||"待专家"}<br/>判据：{p.acceptance_criterion||"待专家"}</span></article>)}</section>{category.notes.map((n,i)=><article key={i} className="rounded-lg border p-3"><h4 className="text-sm font-medium">{n.title} · {n.state==="unknown"?"未知":"AI起草"}</h4><p className="mt-2 whitespace-pre-wrap text-sm leading-6">{n.body}</p><CandidateSources ids={n.citation_ids??[]} citations={citations}/></article>)}<section className="text-sm"><h4 className="font-medium">继续研究的问题</h4><ul className="mt-2 space-y-1">{category.research_questions.map(q=><li key={q}>{q}</li>)}</ul></section><label className="flex items-start gap-2 text-xs leading-5 text-muted-foreground"><input required type="checkbox" checked={shared} onChange={e=>setShared(e.target.checked)}/>我确认这些品类资料可共享，不含客户身份、私有原件和客户专属要求。</label></>}
          {proposal&&<ProposalCandidatePreview document={proposal.document} citations={citations}/>}
        </>}
        {!clarify&&!!citations.length&&<section className="space-y-2 text-sm"><h4 className="font-medium">本次参考资料</h4>{citations.map(c=><a key={c.reference_id} className="block text-primary underline" href={c.href} target="_blank" rel="noreferrer">{c.label}</a>)}</section>}
        {error&&<p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="sticky bottom-0 flex justify-end gap-2 border-t bg-background pt-4"><Button type="button" variant="ghost" disabled={saving} onClick={()=>setOpen(false)}>回到对话</Button><Button disabled={disabled||saving||(!clarify&&!!category&&!shared)}>{saving?"正在保存…":clarify?"回答并继续":category?"保存品类与资料":"保存并打开提案"}</Button></div>
      </form>
    </Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
