"use client";

import { useEffect } from "react";
import { takeCreateIntent, type CreateIntent } from "@/features/shell/lib/command-palette";

/**
 * 目标页面消费 ⌘K 留下的一次性新建意图：只打开页面原有的新建表单，不提交任何内容。
 * "pending" 时保留意图等页面读回权限；"unavailable" 时直接移除，页面照常显示自身的无权限说明。
 */
export function useCreateIntent(intent: CreateIntent, state: "pending" | "ready" | "unavailable", open: () => void) {
  useEffect(() => {
    if (state === "pending" || typeof window === "undefined") return;
    let frame = 0;
    const settle = () => {
      const next = takeCreateIntent(window.location.search, intent);
      if (!next.matched) return;
      window.history.replaceState(window.history.state, "", `${window.location.pathname}${next.search}${window.location.hash}`);
      if (state === "ready") open();
    };
    const check = () => {
      cancelAnimationFrame(frame);
      if (!takeCreateIntent(window.location.search, intent).matched) return;
      // 外壳在导航后会把焦点移到正文；等两帧再打开，焦点才会落在表单里。期间重新渲染会重新排程。
      frame = requestAnimationFrame(() => { frame = requestAnimationFrame(settle); });
    };
    check();
    window.addEventListener("popstate", check);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("popstate", check); };
  }, [intent, state, open]);
}
