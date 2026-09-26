"use client";

import dynamic from "next/dynamic";
import { DeferredPanelLoading, withDeferredPanelBoundary } from "@/components/deferred-panel-loading";

import { useState } from "react";

import type { MyWorkCapaAction } from "./my-work-types";

const NcrWorkspace = withDeferredPanelBoundary(dynamic(() => import("@/components/quality/ncr-workspace").then(module => module.NcrWorkspace), { loading: DeferredPanelLoading }));

export function CapaWorkCard({ item, onChanged, onNotice }: {
  item: MyWorkCapaAction;
  onChanged: () => Promise<void>;
  onNotice: (notice: string) => void;
}) {
  const [loaded, setLoaded] = useState(false);
  return <details className="mx-4 mb-3" onToggle={event => { if (event.currentTarget.open) setLoaded(true); }}>
    <summary className="cursor-pointer text-sm text-primary">查看依据并办理</summary>
    {loaded && <div className="mt-2"><NcrWorkspace projectId={item.project.id} ncrId={item.ncr_id} focusedActionId={item.id} onRecorded={notice => { onNotice(notice); void onChanged(); }}/></div>}
  </details>;
}
