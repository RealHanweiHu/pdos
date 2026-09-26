"use client";

import dynamic from "next/dynamic";
import { DeferredPanelLoading, withDeferredPanelBoundary } from "@/components/deferred-panel-loading";

import { useState } from "react";

import type { WorkFocus } from "@/components/ai/conversation-work-focus";

const ProjectConversation = withDeferredPanelBoundary(dynamic(() => import("@/components/ai/project-conversation").then(module => module.ProjectConversation), { loading: DeferredPanelLoading }));

export function WorkCardConversation({ projectId, kind, id }: { projectId: string } & WorkFocus) {
  const [opened, setOpened] = useState(false);
  return <details className="mx-4 mb-3" onToggle={event => { if (event.currentTarget.open) setOpened(true); }}>
    <summary className="cursor-pointer text-sm text-primary">围绕此项继续提问</summary>
    {opened && <div className="mt-2"><ProjectConversation projectId={projectId} initialWorkFocus={{ kind, id }} defaultOpen/></div>}
  </details>;
}
