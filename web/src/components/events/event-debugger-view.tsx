import { ArrowClockwiseIcon, CaretDownIcon } from "@phosphor-icons/react/ssr";
import { type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { SettingsNav } from "@/components/settings/settings-nav";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import type { DebugEvent, EventDefinition, EventFilters } from "./event-types";

function formatTimestamp(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function EventCard({ event }: { event: DebugEvent }) {
  return (
    <li>
      <article className="rounded-lg border bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted-foreground">#{event.id}</span>
              <h3 className="font-mono text-sm font-semibold text-primary">{event.event_type}</h3>
              <span className="rounded-full bg-muted px-2 py-0.5 font-mono text-[10px] text-muted-foreground">v{event.schema_version}</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{formatTimestamp(event.timestamp)}</p>
          </div>
          <span className="rounded-lg border px-2 py-1 font-mono text-[11px] text-muted-foreground">{event.entity}</span>
        </div>
        <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
          <div><dt className="text-muted-foreground">Source</dt><dd className="mt-1 break-all font-mono">{event.source}</dd></div>
          <div><dt className="text-muted-foreground">Entity ID</dt><dd className="mt-1 break-all font-mono">{event.entity_id}</dd></div>
          <div><dt className="text-muted-foreground">Project ID</dt><dd className="mt-1 break-all font-mono">{event.project_id ?? "—"}</dd></div>
          <div><dt className="text-muted-foreground">Event ID</dt><dd className="mt-1 break-all font-mono">{event.event_id}</dd></div>
        </dl>
        <div className="mt-4 flex flex-wrap gap-1.5" aria-label="Consumers">
          {event.consumers.map((consumer) => (
            <span className="rounded-full bg-accent px-2 py-1 font-mono text-[10px] text-accent-foreground" key={consumer}>{consumer}</span>
          ))}
        </div>
        <details className="group mt-4 rounded-lg border bg-muted/30">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between px-3 text-xs font-medium">
            Payload
            <CaretDownIcon aria-hidden="true" className="transition-transform group-open:rotate-180" />
          </summary>
          <pre className="overflow-x-auto border-t px-3 py-3 text-xs leading-5 whitespace-pre-wrap break-words">{JSON.stringify(event.payload, null, 2)}</pre>
        </details>
      </article>
    </li>
  );
}

export function EventDebuggerView({
  catalog,
  events,
  filters,
  hasMore,
  identity,
  loadingMore,
  loggingOut,
  onApplyFilters,
  onClearFilters,
  onLoadMore,
  onLogout,
  onRefresh,
  streamError,
}: {
  catalog: EventDefinition[];
  events: DebugEvent[];
  filters: EventFilters;
  hasMore: boolean;
  identity: WorkspaceIdentity;
  loadingMore: boolean;
  loggingOut: boolean;
  onApplyFilters: (filters: EventFilters) => void;
  onClearFilters: () => void;
  onLoadMore: () => void;
  onLogout: () => void;
  onRefresh: () => void;
  streamError: string | null;
}) {
  const implemented = catalog.filter((item) => item.implemented_in_sprint_1).length;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    onApplyFilters({
      eventType: String(data.get("event_type") ?? ""),
      projectId: String(data.get("project_id") ?? "").trim(),
    });
  }

  return (
    <WorkspaceShell active="settings" identity={identity} loggingOut={loggingOut} onLogout={onLogout}>
      <SettingsNav current="events" identity={identity}>
      <div className="flex flex-wrap items-start justify-between gap-4 border-b pb-4">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">Internal Debug</p>
          <h1 className="mt-1 text-lg font-semibold">事件流调试</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">按不可变事件 ID 检查 envelope、消费者与 payload。此页面只读，不执行消费者。</p>
        </div>
        <div className="rounded-lg border bg-card px-3 py-2 text-right">
          <p className="font-mono text-sm font-semibold">{implemented} / {catalog.length}</p>
          <p className="text-[11px] text-muted-foreground">Sprint 1 已实现 / 已注册</p>
        </div>
      </div>

      <form className="mt-5 grid gap-3 rounded-lg border bg-card p-4 sm:grid-cols-2 lg:grid-cols-[minmax(180px,1fr)_minmax(240px,1.3fr)_auto]" onSubmit={submit}>
        <label className="grid min-w-0 gap-1.5 text-xs font-medium">
          事件类型
          <select className="h-11 w-full min-w-0 max-w-full rounded-lg border bg-background px-3 text-sm" defaultValue={filters.eventType} key={`type-${filters.eventType}`} name="event_type">
            <option value="">全部类型</option>
            {catalog.map((definition) => <option key={definition.event_type} value={definition.event_type}>{definition.event_type}</option>)}
          </select>
        </label>
        <label className="grid min-w-0 gap-1.5 text-xs font-medium">
          项目 ID
          <input className="h-11 w-full min-w-0 max-w-full rounded-lg border bg-background px-3 font-mono text-sm" defaultValue={filters.projectId} key={`project-${filters.projectId}`} name="project_id" placeholder="可选 UUID" />
        </label>
        <div className="flex min-w-0 flex-wrap items-end gap-2 sm:col-span-2 lg:col-span-1">
          <Button className="h-11" type="submit">应用筛选</Button>
          <Button className="h-11" onClick={onClearFilters} type="button" variant="outline">清除筛选</Button>
          <Button aria-label="刷新事件流" className="size-11" onClick={onRefresh} size="icon" type="button" variant="ghost"><ArrowClockwiseIcon aria-hidden="true" /></Button>
        </div>
      </form>

      {streamError ? <p className="mt-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{streamError}</p> : null}
      {events.length === 0 ? (
        <section className="mt-5 rounded-lg border border-dashed px-4 py-12 text-center">
          <h2 className="font-medium">当前筛选没有事件</h2>
          <p className="mt-1 text-sm text-muted-foreground">更改条件或刷新事件流。</p>
        </section>
      ) : (
        <ul className="mt-5 space-y-3" role="list">{events.map((event) => <EventCard event={event} key={event.id} />)}</ul>
      )}
      {hasMore ? <div className="mt-5 flex justify-center"><Button className="h-11" disabled={loadingMore} onClick={onLoadMore} variant="outline">{loadingMore ? "正在加载…" : "加载更多"}</Button></div> : null}
      </SettingsNav>
    </WorkspaceShell>
  );
}
