"use client";
import { useSearchParams } from "next/navigation";
import { ProjectCrossDependencies } from "./project-cross-dependencies";

export function CrossProposalLanding({projectId}:{projectId:string}) {
  const search=useSearchParams();
  const id=search.get("project")===projectId?search.get("cross_proposal"):null;
  if(!id||!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id))return null;
  return <section id="cross-proposal-landing" className="space-y-2" aria-label="原跨项目排程确认申请"><h3 className="font-semibold">原跨项目排程确认</h3><ProjectCrossDependencies key={`${projectId}:${id}`} projectId={projectId} focusProposalId={id}/></section>;
}
