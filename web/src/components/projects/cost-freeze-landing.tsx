"use client";

import { useSearchParams } from "next/navigation";
import { CostFreezes } from "./cost-freezes";

export function CostFreezeLanding({projectId,canEdit}:{projectId:string;canEdit:boolean}) {
  const search=useSearchParams();
  const id=search.get("project")===projectId?search.get("cost_freeze_request"):null;
  if(!id||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id))return null;
  return <section id="cost-freeze-landing" className="space-y-2" aria-label="原成本冻结待批申请"><h3 className="font-semibold">原成本批准申请</h3><CostFreezes key={`${projectId}:${id}`} projectId={projectId} canEdit={canEdit} calculation={null} initialRequestId={id}/></section>;
}
