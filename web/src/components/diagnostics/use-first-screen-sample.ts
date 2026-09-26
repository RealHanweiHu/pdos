"use client";

import { useEffect } from "react";

type Page = "my-work" | "project" | "review";
type State = "loading" | "ready" | "error";

/** Local, explicitly enabled engineering measurement. No storage or outbound telemetry. */
export function useFirstScreenSample(page: Page, state: State, counts: Record<string, number>) {
  const summary = JSON.stringify(counts);
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_PDOS_UX10_DIAGNOSTICS !== "1"
      || !["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname)) return;
    const sample = new URLSearchParams(window.location.search).get("ux_probe");
    if (!sample || !/^[a-z0-9-]{1,80}$/.test(sample)) return;
    let output = document.querySelector<HTMLOutputElement>('[data-testid="ux10-sample"]');
    if (output?.dataset.done === "true") return;
    if (!output) {
      output = document.createElement("output");
      output.hidden = true;
      output.dataset.testid = "ux10-sample";
      document.body.append(output);
    }
    const target = output;
    const navigation = performance.getEntriesByType("navigation")[0] as PerformanceNavigationTiming | undefined;
    const url = new URL(window.location.href);
    const fullNavigation = navigation && new URL(navigation.name).pathname === url.pathname
      && new URL(navigation.name).search === url.search;
    let frame = 0;
    let timer = 0;
    const finish = (status: "ready" | "error" | "timeout" | "unsupported") => {
      if (target.dataset.done === "true") return;
      const resources = (performance.getEntriesByType("resource") as PerformanceResourceTiming[])
        .filter(entry => new URL(entry.name).origin === url.origin && new URL(entry.name).pathname.startsWith("/api/"))
        .map(entry => ({ path: new URL(entry.name).pathname, startMs: entry.startTime,
          endMs: entry.responseEnd, durationMs: entry.duration, responseStatus: entry.responseStatus }));
      const selectors = page === "project"
        ? ['[aria-label="项目概览"]', '[aria-label="项目概览"] button', '[data-metric="task"]']
        : page === "my-work" ? ['[data-testid="my-work-ready"]', 'main a[href^="#work-task-"]', 'main a[href^="#work-task-"]']
          : ['[data-testid="ai-review-ready"]', 'main h2', 'main footer button:first-of-type'];
      const elements = selectors.map(selector => {
        const element = document.querySelector<HTMLElement>(selector);
        const rect = element?.getBoundingClientRect();
        return { selector, present: !!element, enabled: !!element && !element.matches(":disabled"), top: rect?.top ?? null,
          visible: !!rect && rect.width > 0 && rect.height > 0 && rect.top >= 0 && rect.left >= 0
            && rect.bottom <= window.innerHeight && rect.right <= window.innerWidth };
      });
      target.textContent = JSON.stringify({ protocol: "ux10-local-v2", sample, page, status,
        elapsedMs: performance.now(), timeOrigin: performance.timeOrigin, state,
        counts: JSON.parse(summary), visibility: document.visibilityState,
        viewport: { width: window.innerWidth, height: window.innerHeight, scale: window.devicePixelRatio },
        userAgent: navigator.userAgent, navigationType: navigation?.type ?? null,
        fullNavigation: !!fullNavigation, resources, elements });
      target.dataset.done = "true";
      window.clearTimeout(timer);
    };
    target.textContent = JSON.stringify({ sample, page, status: "loading" });
    if (!fullNavigation) finish("unsupported");
    else if (state === "error") finish("error");
    else {
      timer = window.setTimeout(() => finish("timeout"), Math.max(0, 10000 - performance.now()));
      if (state === "ready") {
        const project = url.searchParams.get("project");
        const required = page === "my-work"
          ? ["/api/session/me", "/api/me/work", "/api/me/notifications", "/api/product-work/my-work"]
          : page === "review"
            ? ["/api/session/me", "/api/projects", "/api/ai/findings", "/api/ai/review-inbox", "/api/ai/risk-candidates", "/api/ai/findings/archive-policy"]
            : ["/api/session/me", "/api/projects", ...["tasks", "issues", "risks", "activity", "knowledge-prepared"].map(part => `/api/projects/${project}/${part}`), `/api/ai/projects/${project}/runs`];
        const awaitReads = () => {
          const entries = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
          const completed = required.map(path => entries.find(entry => new URL(entry.name).origin === url.origin && new URL(entry.name).pathname === path));
          const supplementary = page === "my-work" ? document.querySelector<HTMLElement>("[data-preproject-state]")?.dataset.preprojectState : "ready";
          if (supplementary === "error" || completed.some(entry => entry && entry.responseStatus >= 400)) finish("error");
          else if (completed.every(entry => entry && entry.responseEnd > 0 && entry.responseStatus === 200) && supplementary === "ready") {
            frame = requestAnimationFrame(() => {
              frame = requestAnimationFrame(() => finish(performance.now() <= 10000 ? "ready" : "timeout"));
            });
          } else if (target.dataset.done !== "true") frame = requestAnimationFrame(awaitReads);
        };
        frame = requestAnimationFrame(awaitReads);
      }
    }
    return () => { cancelAnimationFrame(frame); window.clearTimeout(timer); };
  }, [page, state, summary]);
}
