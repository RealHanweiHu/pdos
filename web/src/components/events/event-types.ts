export type EventDefinition = {
  event_type: string;
  version: number;
  entity: string;
  producer: string;
  consumers: string[];
  payload_schema: Record<string, unknown>;
  idempotency: string;
  implemented_in_sprint_1: boolean;
};

export type DebugEvent = {
  id: number;
  project_id: string | null;
  event_id: string;
  event_type: string;
  schema_version: number;
  source: string;
  entity: string;
  entity_id: string;
  payload: Record<string, unknown>;
  timestamp: string;
  consumers: string[];
};

export type EventPage = {
  items: DebugEvent[];
  next_after_id: number | null;
  has_more: boolean;
};

export type EventFilters = {
  eventType: string;
  projectId: string;
};
