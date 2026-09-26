"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { noticeCall } from "@/components/projects/supplier-notice-applications";
import { CostDefinitionFeedback } from "@/components/projects/cost-definition-feedback";

export function DefinitionCostFeedback({spaceId,definitionId}:{spaceId:string;definitionId:string}) {
  const [data,setData]=useState<Row|null>(null),[selected,setSelected]=useState<Row|null>(null),[error,setError]=useState(""),[busy,setBusy]=useState(false);
  async function load(before?:string){setBusy(true);setError("");try{setData(await noticeCall(`/api/product-work/spaces/${spaceId}/definitions/${definitionId}/cost-feedback${before?`?before=${before}`:""}`));}catch(e){setError(e instanceof Error?e.message:"反馈读取未完成");}finally{setBusy(false);}}
  return <details className="rounded-md border p-3" onToggle={e=>{if(e.currentTarget.open&&!data&&!busy)void load();}}><summary className="cursor-pointer text-sm font-medium">实际项目成本反馈</summary><div className="mt-3 space-y-3 text-xs"><p>本定义系列的Cost Gap、降本方案及历史／实际成本回测反馈。仅展示同时有权读取的原项目资料；创建或编辑定义修订后可关联实际版本，协审和发布仍沿原流程。</p>{error&&<p role="alert" className="text-destructive">{error}</p>}<Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void load()}>刷新成本反馈</Button>{data&&rows(data.items).length===0&&<p>此页没有可读取的成本反馈。</p>}{rows(data?.items).map(v=><div className="space-y-2 rounded-md bg-muted/30 p-2" key={text(v.id)}><p>{text(v.definition_title)} · {text(v.finding)}</p><p>{({needs_information:"待补资料",no_change:"维持原定义",link_revision:"已关联实际修订"} as Record<string,string>)[text(obj(v.latest_decision).action)]??"待处理"}</p><Button type="button" size="sm" variant="outline" onClick={()=>setSelected(v)}>查看原成本／产品经理处置</Button></div>)}{data?.next_cursor!=null&&<Button type="button" size="sm" variant="outline" disabled={busy} onClick={()=>void load(text(data.next_cursor))}>继续查看更早反馈</Button>}{selected&&<CostDefinitionFeedback key={text(selected.id)} projectId={text(selected.project_id)} initialId={text(selected.id)}/>}</div></details>;
}
