"use client";

import { CaretRightIcon } from "@phosphor-icons/react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

export type ProjectWorkSection = {
  id: string;
  title: string;
  description?: string;
  children: ReactNode;
  queryKeys?: string[];
  hashPrefixes?: string[];
};

type LocationRule = Pick<ProjectWorkSection, "id" | "queryKeys" | "hashPrefixes">;

/** Progressive disclosure keeps every domain panel mounted, including drafts. */
export function ProjectWorkSections({
  label,
  sections,
  defaultOpen,
}: {
  label: string;
  sections: ProjectWorkSection[];
  defaultOpen?: string[];
}) {
  const root = useRef<HTMLElement>(null);
  const details = useRef(new Map<string, HTMLDetailsElement>());
  const instanceId = useId();
  // This is an initial attribute. Native details owns subsequent user toggles;
  // unchanged defaults never overwrite those choices when a panel refreshes.
  const [initiallyOpen] = useState(() => new Set(defaultOpen ?? sections.slice(0, 1).map(section => section.id)));
  // Parent panels recreate their content after reads. Only navigation rules,
  // rather than children or object identity, should reinstall URL listeners.
  const locationRules = JSON.stringify(sections.map(({ id, queryKeys, hashPrefixes }) => ({ id, queryKeys, hashPrefixes })));

  useEffect(() => {
    const container = root.current;
    if (!container) return;
    const rules: LocationRule[] = JSON.parse(locationRules);
    let observer: MutationObserver | null = null;
    let scrollFrame: number | null = null;

    const revealLocation = () => {
      observer?.disconnect();
      observer = null;
      if (scrollFrame !== null) cancelAnimationFrame(scrollFrame);
      scrollFrame = null;
      const query = new URLSearchParams(window.location.search);
      let anchor = window.location.hash.slice(1);
      try { anchor = decodeURIComponent(anchor); } catch { /* Keep a malformed fragment literal. */ }

      for (const rule of rules) {
        const requested = rule.queryKeys?.some(key => query.has(key)) ||
          !!anchor && (anchor === rule.id || rule.hashPrefixes?.some(prefix => {
            const normalized = prefix.replace(/^#/, "");
            return !!normalized && anchor.startsWith(normalized);
          }));
        if (requested) {
          const section = details.current.get(rule.id);
          if (section) section.open = true;
        }
      }
      if (!anchor) return;

      const revealAnchor = () => {
        const target = document.getElementById(anchor) ?? details.current.get(anchor);
        if (!target || !container.contains(target)) return false;
        // Old receipts may land inside nested disclosures in a domain panel.
        // Reveal all of those ancestors before measuring the scroll position.
        for (let ancestor: HTMLElement | null = target; ancestor && ancestor !== container; ancestor = ancestor.parentElement) {
          if (ancestor instanceof HTMLDetailsElement) ancestor.open = true;
        }
        scrollFrame = requestAnimationFrame(() => {
          target.scrollIntoView?.({ block: "start" });
          scrollFrame = null;
        });
        return true;
      };
      if (revealAnchor()) return;
      // A deferred panel can supply the anchor later. Observe only this
      // workspace, only until its target appears; never poll or change the URL.
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
      window.removeEventListener("popstate", revealLocation);
      window.removeEventListener("hashchange", revealLocation);
      observer?.disconnect();
      if (scrollFrame !== null) cancelAnimationFrame(scrollFrame);
    };
  }, [locationRules]);

  return (
    <section aria-label={label} className="min-w-0 space-y-4" ref={root}>
      {sections.map(section => (
        <details
          className="group/work-section min-w-0 scroll-mt-28 border-t pt-1 first:border-t-0 first:pt-0"
          key={section.id}
          open={initiallyOpen.has(section.id)}
          ref={element => {
            if (element) details.current.set(section.id, element);
            else details.current.delete(section.id);
          }}
        >
          <summary
            aria-controls={`${instanceId}-${section.id}-content`}
            className="flex min-h-11 cursor-pointer list-none items-start gap-2.5 rounded-lg px-2 py-3 transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden"
          >
            <CaretRightIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform duration-150 group-open/work-section:rotate-90 motion-reduce:transition-none" />
            <span className="min-w-0 flex-1">
              <span className="block break-words text-sm font-semibold [overflow-wrap:anywhere]">{section.title}</span>
              {section.description && <span className="mt-1 block break-words text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]">{section.description}</span>}
            </span>
            <span className="shrink-0 pt-0.5 text-xs text-muted-foreground">
              <span className="group-open/work-section:hidden">展开办理</span>
              <span className="hidden group-open/work-section:inline">收起办理</span>
            </span>
          </summary>
          <div className="min-w-0 space-y-4 pb-4 pt-2" id={`${instanceId}-${section.id}-content`}>
            {section.children}
          </div>
        </details>
      ))}
    </section>
  );
}
