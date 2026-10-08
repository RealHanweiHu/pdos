"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { request } from "./product-work-api";
import { proposalField as field } from "./proposal-entry";
import type { Proposal } from "./proposal-types";

export function CustomerKnowledgePromotion({base,proposal,onError,onPendingChange}:{base:string;proposal:Proposal;onError:(e:unknown)=>void;onPendingChange:(v:boolean)=>void}) {
  const [busy,setBusy]=useState(false),[done,setDone]=useState(false);
  const original=useRef({key:"",id:""});
  return <details className="rounded-lg border p-4"><summary className="cursor-pointer text-sm font-medium">将去标识后的共性结论沉淀到品类</summary><p className="mt-2 text-xs text-muted-foreground">手工写共性摘要。客户身份、原件、链接和客户专属要求继续留在提案内。</p><form className="mt-3 space-y-3" onSubmit={async e=>{e.preventDefault();if(busy)return;const f=new FormData(e.currentTarget);const body={kind:"general_requirement",title:String(f.get("title")),body:String(f.get("body")),proposal_id:proposal.id,expected_proposal_version:proposal.version,confirmed_anonymized:f.get("confirmed")==="on"};const key=JSON.stringify(body);if(original.current.key!==key)original.current={key,id:crypto.randomUUID()};setBusy(true);onPendingChange(true);setDone(false);try{await request(`categories/${base.split("/")[1]}/shared/knowledge`,"POST",{...body,request_id:original.current.id});setDone(true);}catch(error){onError(error);}finally{setBusy(false);onPendingChange(false);}}}><input name="title" aria-label="共性结论标题" required maxLength={256} placeholder="例如：欧美市场噪声要求" className={field} disabled={busy}/><textarea name="body" aria-label="去标识后的共性摘要" required maxLength={8000} rows={3} placeholder="例如：多个欧美客户要求工作噪声≤75 dB(A)。" className={field} disabled={busy}/><label className="flex items-start gap-2 text-xs"><input name="confirmed" type="checkbox" required disabled={busy}/>我已移除客户身份、原件链接和专属要求，确认这份摘要可供品类成员共享。</label><Button size="sm" disabled={busy}>具名确认并沉淀</Button>{done&&<p role="status" className="text-xs text-muted-foreground">共性摘要已加入品类；客户原件仍留在提案内。</p>}</form></details>;
}
