import { isRecord, requestIdentity, responseBody } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import type { DebugEvent, EventDefinition, EventFilters, EventPage } from "./event-types";

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isDefinition(value: unknown): value is EventDefinition {
  return (
    isRecord(value) &&
    typeof value.event_type === "string" &&
    typeof value.version === "number" &&
    typeof value.entity === "string" &&
    typeof value.producer === "string" &&
    isStringArray(value.consumers) &&
    isRecord(value.payload_schema) &&
    typeof value.idempotency === "string" &&
    typeof value.implemented_in_sprint_1 === "boolean"
  );
}

function isDebugEvent(value: unknown): value is DebugEvent {
  return (
    isRecord(value) &&
    typeof value.id === "number" &&
    Number.isSafeInteger(value.id) &&
    (typeof value.project_id === "string" || value.project_id === null) &&
    typeof value.event_id === "string" &&
    typeof value.event_type === "string" &&
    typeof value.schema_version === "number" &&
    typeof value.source === "string" &&
    typeof value.entity === "string" &&
    typeof value.entity_id === "string" &&
    isRecord(value.payload) &&
    typeof value.timestamp === "string" &&
    isStringArray(value.consumers)
  );
}

function parseCatalog(value: unknown): EventDefinition[] {
  if (!isRecord(value) || !Array.isArray(value.items) || !value.items.every(isDefinition)) {
    throw new Error("invalid event catalog");
  }
  return value.items;
}

function parsePage(value: unknown): EventPage {
  if (
    !isRecord(value) ||
    !Array.isArray(value.items) ||
    !value.items.every(isDebugEvent) ||
    (typeof value.next_after_id !== "number" && value.next_after_id !== null) ||
    typeof value.has_more !== "boolean"
  ) {
    throw new Error("invalid event page");
  }
  return value as EventPage;
}

export async function requestEventPage(
  filters: EventFilters,
  afterId: number | null = null,
): Promise<EventPage> {
  const query = new URLSearchParams({ limit: "50" });
  if (afterId !== null) query.set("after_id", String(afterId));
  if (filters.eventType) query.set("event_type", filters.eventType);
  if (filters.projectId) query.set("project_id", filters.projectId);
  const response = await fetch(`/api/events?${query.toString()}`, {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (!response.ok) throw new Error("event stream unavailable");
  return parsePage(await responseBody(response));
}

export type EventDebugBootstrap =
  | { kind: "ready"; identity: WorkspaceIdentity; catalog: EventDefinition[]; page: EventPage }
  | { kind: "forbidden"; identity: WorkspaceIdentity }
  | null;

export async function requestEventDebugBootstrap(): Promise<EventDebugBootstrap> {
  const identity = await requestIdentity();
  if (identity === null) return null;
  if (!['owner', 'admin'].includes(identity.user.role)) {
    return { kind: "forbidden", identity };
  }
  const [catalogResponse, page] = await Promise.all([
    fetch("/api/events/catalog", { cache: "no-store", credentials: "same-origin" }),
    requestEventPage({ eventType: "", projectId: "" }),
  ]);
  if (!catalogResponse.ok) throw new Error("event catalog unavailable");
  return {
    kind: "ready",
    identity,
    catalog: parseCatalog(await responseBody(catalogResponse)),
    page,
  };
}
