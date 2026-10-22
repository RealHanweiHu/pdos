"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

export type ProjectTaskSection = {
  id: string;
  title: string;
  description?: string;
  children: ReactNode;
  queryKeys?: string[];
  hashPrefixes?: string[];
};

type LocationRule = Pick<ProjectTaskSection, "id" | "queryKeys" | "hashPrefixes">;

/** One task at a time; all domain forms remain mounted between tasks. */
export function ProjectTaskWorkspace({
  label,
  sections,
  defaultOpen,
}: {
  label: string;
  sections: ProjectTaskSection[];
  defaultOpen?: string[];
}) {
  const instanceId = useId();
  const root = useRef<HTMLElement>(null);
  const panels = useRef(new Map<string, HTMLDivElement>());
  const tabs = useRef(new Map<string, HTMLButtonElement>());
  const cancelLocation = useRef<() => void>(() => {});
  const lastLocation = useRef<string | null>(null);
  const pendingAnchor = useRef<string | null>(null);
  const [activeId, setActiveId] = useState(() => sections.find(section => section.id === defaultOpen?.[0])?.id ?? sections[0]?.id ?? "");
  const active = sections.find(section => section.id === activeId) ?? sections[0];
  const [verticalNavigation, setVerticalNavigation] = useState(false);
  const locationRules = JSON.stringify(sections.map(({ id, queryKeys, hashPrefixes }) => ({ id, queryKeys, hashPrefixes })));

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(min-width: 1280px)");
    const update = () => setVerticalNavigation(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    const container = root.current;
    if (!container) return;
    const rules: LocationRule[] = JSON.parse(locationRules);
    let observer: MutationObserver | null = null;
    let scrollFrame: number | null = null;
    const stop = () => {
      observer?.disconnect();
      observer = null;
      if (scrollFrame !== null) cancelAnimationFrame(scrollFrame);
      scrollFrame = null;
    };
    cancelLocation.current = stop;

    const revealLocation = () => {
      stop();
      const location = `${window.location.pathname}${window.location.search}${window.location.hash}`;
      const isNavigation = lastLocation.current !== location;
      lastLocation.current = location;
      // A domain read can change its children and rules. A same-URL refresh
      // must keep the task the person chose, including an unsubmitted draft.
      if (!isNavigation && !pendingAnchor.current) return;

      const query = new URLSearchParams(window.location.search);
      let anchor = window.location.hash.slice(1);
      try { anchor = decodeURIComponent(anchor); } catch { /* Keep a malformed fragment literal. */ }
      const hashRule = anchor ? rules.find(rule => anchor === rule.id || rule.hashPrefixes?.some(prefix => {
        const normalized = prefix.replace(/^#/, "");
        return !!normalized && anchor.startsWith(normalized);
      })) : undefined;
      const queryRule = rules.find(rule => rule.queryKeys?.some(key => query.has(key)));
      const requested = hashRule ?? queryRule;
      if (isNavigation && requested) setActiveId(requested.id);
      pendingAnchor.current = anchor || null;
      if (!anchor) return;

      const revealAnchor = () => {
        // Scope lookup to this workspace even when the page has another
        // element with the same legacy receipt ID.
        const target = Array.from(container.querySelectorAll<HTMLElement>("[id]")).find(element => element.id === anchor);
        if (!target) return false;
        const owner = rules.find(rule => panels.current.get(rule.id)?.contains(target));
        if (!owner) return false;
        setActiveId(owner.id);
        for (let ancestor: HTMLElement | null = target; ancestor && ancestor !== container; ancestor = ancestor.parentElement) {
          if (ancestor instanceof HTMLDetailsElement) ancestor.open = true;
        }
        pendingAnchor.current = null;
        scrollFrame = requestAnimationFrame(() => {
          target.scrollIntoView?.({ block: "start" });
          scrollFrame = null;
        });
        return true;
      };
      if (revealAnchor()) return;
      observer = new MutationObserver(() => {
        if (revealAnchor()) {
          observer?.disconnect();
          observer = null;
        }
      });
      observer.observe(container, { childList: true, subtree: true, attributes: true, attributeFilter: ["id"] });
    };

    revealLocation();
    window.addEventListener("popstate", revealLocation);
    window.addEventListener("hashchange", revealLocation);
    return () => {
      stop();
      window.removeEventListener("popstate", revealLocation);
      window.removeEventListener("hashchange", revealLocation);
    };
  }, [locationRules]);

  const selectTask = (id: string, focus = false) => {
    cancelLocation.current();
    pendingAnchor.current = null;
    setActiveId(id);
    const nextLocation = `${window.location.pathname}${window.location.search}#${encodeURIComponent(id)}`;
    const currentLocation = `${window.location.pathname}${window.location.search}${window.location.hash}`;
    if (nextLocation !== currentLocation) window.history.pushState(window.history.state, "", nextLocation);
    lastLocation.current = nextLocation;
    if (focus) tabs.current.get(id)?.focus();
  };

  const navigateTask = (event: KeyboardEvent<HTMLButtonElement>) => {
    const currentIndex = sections.findIndex(section => section.id === active?.id);
    let nextIndex: number;
    if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = sections.length - 1;
    else if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (currentIndex + 1) % sections.length;
    else if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (currentIndex - 1 + sections.length) % sections.length;
    else return;
    event.preventDefault();
    if (sections[nextIndex]) selectTask(sections[nextIndex].id, true);
  };

  return (
    <section aria-label={label} className="grid min-w-0 max-w-full gap-5 xl:grid-cols-[220px_minmax(0,1fr)]" ref={root}>
      <div
        aria-label={`${label}任务`}
        aria-orientation={verticalNavigation ? "vertical" : "horizontal"}
        className="flex min-w-0 max-w-full gap-1 overflow-x-auto border-b pb-2 xl:sticky xl:top-20 xl:flex-col xl:self-start xl:overflow-visible xl:border-r xl:border-b-0 xl:pb-0 xl:pr-4"
        role="tablist"
      >
        {sections.map(section => (
          <button
            aria-controls={section.id}
            aria-selected={active?.id === section.id}
            className="min-h-11 shrink-0 rounded-lg px-3 py-2.5 text-left text-sm leading-5 transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-selected:bg-accent aria-selected:font-semibold aria-selected:text-accent-foreground xl:w-full xl:whitespace-normal"
            id={`${instanceId}-${section.id}-task`}
            key={section.id}
            onClick={() => selectTask(section.id)}
            onKeyDown={navigateTask}
            ref={element => {
              if (element) tabs.current.set(section.id, element);
              else tabs.current.delete(section.id);
            }}
            role="tab"
            tabIndex={active?.id === section.id ? 0 : -1}
            type="button"
          >
            {section.title}
          </button>
        ))}
      </div>
      <div className="min-w-0 space-y-5">
        {sections.map(section => (
          <div
            aria-labelledby={`${instanceId}-${section.id}-task`}
            className="min-w-0 scroll-mt-28 space-y-5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            hidden={active?.id !== section.id}
            id={section.id}
            key={section.id}
            ref={element => {
              if (element) panels.current.set(section.id, element);
              else panels.current.delete(section.id);
            }}
            role="tabpanel"
            tabIndex={0}
          >
            <header className="space-y-1.5 border-b pb-4">
              <h2 className="break-words text-base font-semibold [overflow-wrap:anywhere]">{section.title}</h2>
              {section.description && <p className="max-w-3xl break-words text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]">{section.description}</p>}
            </header>
            <div className="min-w-0 space-y-5">{section.children}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
