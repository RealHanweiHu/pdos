"use client";

import { useRef, useState } from "react";
import { requestMyWork } from "./my-work-api";
import type { MyWork, MyWorkCollection } from "./my-work-types";

const collections: MyWorkCollection[] = ["tasks", "issues", "risks", "capa_actions", "gate_signoffs", "findings", "cross_schedule_approvals", "id_design_actions", "change_execution_confirmations", "risk_followup_actions", "task_takeover_actions", "cost_freeze_approvals"];

function combine(current: MyWork, page: MyWork, name: MyWorkCollection, append: boolean): MyWork {
  const cursor = page.pages?.[name];
  if (append && (!cursor || cursor.offset !== (current[name] ?? []).length || cursor.revision !== current.pages?.[name]?.revision)) {
    throw new Error("待办分页范围已变化，请刷新本类工作。");
  }
  return {
    ...current,
    [name]: append ? [...(current[name] ?? []), ...(page[name] ?? [])] : (page[name] ?? []),
    counts: { ...current.counts, [name]: page.counts[name] ?? 0 },
    pages: { ...current.pages, [name]: cursor },
  };
}

async function readPage(options?: Parameters<typeof requestMyWork>[0]) {
  const page = await requestMyWork(options);
  if (!page) throw new Error("登录已失效，请重新登录后读取工作列表。");
  return page;
}

// Refresh as much as the user has already opened; keep unaffected collections
// and their mounted forms. A changing queue never silently skips an offset.
async function fillLoadedRange(base: MyWork, name: MyWorkCollection, target: number) {
  let result = base;
  while ((result[name] ?? []).length < target) {
    const cursor = result.pages?.[name];
    if (!cursor || cursor.next_offset === null) break;
    const page = await readPage({ collection: name, offset: cursor.next_offset, expected_revision: cursor.revision, limit: Math.min(200, target - (result[name] ?? []).length) });
    result = combine(result, page, name, true);
  }
  return result;
}

export function useMyWorkQueue(initial: MyWork) {
  const [work, setWork] = useState(initial);
  const [busy, setBusy] = useState<MyWorkCollection | "refresh" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestVersion = useRef(0);
  const reading = useRef(false);

  async function refresh(name?: MyWorkCollection): Promise<boolean> {
    const version = ++requestVersion.current;
    reading.current = true;
    setBusy(name ?? "refresh"); setError(null);
    try {
      const page = await readPage(name ? { collection: name, limit: Math.min(200, Math.max(50, (work[name] ?? []).length)) } : undefined);
      let next = name ? combine(work, page, name, false) : page;
      for (const key of name ? [name] : collections) {
        if (version !== requestVersion.current) return false;
        if (!name && work.pages?.[key]?.revision && work.pages[key]?.revision === page.pages?.[key]?.revision) {
          next = combine(next, work, key, false);
        } else {
          next = await fillLoadedRange(next, key, (work[key] ?? []).length);
        }
      }
      if (version !== requestVersion.current) return false;
      setWork(next);
      return true;
    } catch (failure) {
      if (version === requestVersion.current) setError(failure instanceof Error ? failure.message : "工作列表刷新失败，请重试。");
      return false;
    } finally {
      if (version === requestVersion.current) { reading.current = false; setBusy(null); }
    }
  }

  async function loadMore(name: MyWorkCollection) {
    const cursor = work.pages?.[name];
    if (reading.current || !cursor || cursor.next_offset === null) return;
    const version = ++requestVersion.current;
    reading.current = true; setBusy(name); setError(null);
    try {
      const page = await readPage({ collection: name, offset: cursor.next_offset, expected_revision: cursor.revision, limit: 50 });
      if (version === requestVersion.current) setWork(combine(work, page, name, true));
    } catch (failure) {
      if (version === requestVersion.current) setError(failure instanceof Error ? failure.message : "更多工作加载失败，请重试。");
    } finally {
      if (version === requestVersion.current) { reading.current = false; setBusy(null); }
    }
  }
  return { work, busy, error, refresh, loadMore };
}
