"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { WorkspaceIdentity } from "@/components/workspace-types";

import { requestEventDebugBootstrap, requestEventPage } from "./event-api";
import { EventDebuggerError, EventDebuggerForbidden, EventDebuggerLoading } from "./event-debugger-state";
import { EventDebuggerView } from "./event-debugger-view";
import type { DebugEvent, EventDefinition, EventFilters } from "./event-types";

type LoadState = "loading" | "ready" | "forbidden" | "error" | "redirecting";
const EMPTY_FILTERS: EventFilters = { eventType: "", projectId: "" };

export function EventDebugger() {
  const { replace } = useRouter();
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [catalog, setCatalog] = useState<EventDefinition[]>([]);
  const [events, setEvents] = useState<DebugEvent[]>([]);
  const [filters, setFilters] = useState<EventFilters>(EMPTY_FILTERS);
  const [nextAfterId, setNextAfterId] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);

  async function load() {
    try {
      const loaded = await requestEventDebugBootstrap();
      if (loaded === null) {
        setLoadState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loaded.identity);
      if (loaded.kind === "forbidden") {
        setLoadState("forbidden");
        return;
      }
      setCatalog(loaded.catalog);
      setEvents(loaded.page.items);
      setNextAfterId(loaded.page.next_after_id);
      setHasMore(loaded.page.has_more);
      setFilters(EMPTY_FILTERS);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }

  useEffect(() => {
    let active = true;
    requestEventDebugBootstrap().then(
      (loaded) => {
        if (!active) return;
        if (loaded === null) {
          setLoadState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(loaded.identity);
        if (loaded.kind === "forbidden") {
          setLoadState("forbidden");
          return;
        }
        setCatalog(loaded.catalog);
        setEvents(loaded.page.items);
        setNextAfterId(loaded.page.next_after_id);
        setHasMore(loaded.page.has_more);
        setFilters(EMPTY_FILTERS);
        setLoadState("ready");
      },
      () => {
        if (active) setLoadState("error");
      },
    );
    return () => {
      active = false;
    };
  }, [replace]);

  async function replaceStream(nextFilters: EventFilters) {
    setStreamError(null);
    try {
      const page = await requestEventPage(nextFilters);
      setFilters(nextFilters);
      setEvents(page.items);
      setNextAfterId(page.next_after_id);
      setHasMore(page.has_more);
    } catch {
      setStreamError("无法读取该筛选条件下的事件流。");
    }
  }

  async function loadMore() {
    if (nextAfterId === null) return;
    setLoadingMore(true);
    setStreamError(null);
    try {
      const page = await requestEventPage(filters, nextAfterId);
      setEvents((current) => {
        const known = new Set(current.map((item) => item.id));
        return [...current, ...page.items.filter((item) => !known.has(item.id))];
      });
      setNextAfterId(page.next_after_id);
      setHasMore(page.has_more);
    } catch {
      setStreamError("无法继续读取事件流。");
    } finally {
      setLoadingMore(false);
    }
  }

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      replace("/login");
    }
  }

  if (loadState === "redirecting") return null;
  if (loadState === "loading") return <EventDebuggerLoading />;
  if (loadState === "error" || identity === null) {
    return <EventDebuggerError onRetry={() => { setLoadState("loading"); void load(); }} />;
  }
  if (loadState === "forbidden") {
    return <EventDebuggerForbidden identity={identity} loggingOut={loggingOut} onLogout={() => void logout()} />;
  }
  return (
    <EventDebuggerView
      catalog={catalog}
      events={events}
      filters={filters}
      hasMore={hasMore}
      identity={identity}
      loadingMore={loadingMore}
      loggingOut={loggingOut}
      onApplyFilters={(nextFilters) => void replaceStream(nextFilters)}
      onClearFilters={() => void replaceStream(EMPTY_FILTERS)}
      onLoadMore={() => void loadMore()}
      onLogout={() => void logout()}
      onRefresh={() => void replaceStream(filters)}
      streamError={streamError}
    />
  );
}
