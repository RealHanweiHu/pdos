"use client";

import { Component, type ComponentType, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

export function DeferredPanelLoading() {
  return <p role="status" className="py-3 text-sm text-muted-foreground">正在载入办理区域…</p>;
}

class PanelBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <div role="alert" className="space-y-2 rounded-md border p-3 text-sm"><p>此办理区域暂不可用，其他区域仍可使用。重新载入页面会清除未提交内容，请先保留。</p><Button type="button" size="sm" variant="outline" onClick={() => window.location.reload()}>重新载入页面</Button></div>;
    return this.props.children;
  }
}

export function withDeferredPanelBoundary<P extends object>(Panel: ComponentType<P>) {
  return function DeferredPanel(props: P) {
    return <PanelBoundary><Panel {...props}/></PanelBoundary>;
  };
}
