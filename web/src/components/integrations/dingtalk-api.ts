import { isRecord, requestIdentity, responseBody } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import type { DingTalkBootstrap, DingTalkOutboxItem, DingTalkStatus } from "./dingtalk-types";

const INTERNAL_ROLES = new Set(["owner", "admin", "project_manager", "engineer", "quality"]);

function parseStatus(value: unknown): DingTalkStatus {
  if (
    !isRecord(value) ||
    typeof value.configured !== "boolean" ||
    !(typeof value.binding_status === "string" || value.binding_status === null) ||
    !(typeof value.corp_id === "string" || value.corp_id === null) ||
    typeof value.linked !== "boolean" ||
    typeof value.delivery_enabled !== "boolean"
  ) {
    throw new Error("invalid DingTalk status");
  }
  return value as DingTalkStatus;
}

function parseOutboxItem(value: unknown): DingTalkOutboxItem {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    !(typeof value.project_id === "string" || value.project_id === null) ||
    typeof value.operation !== "string" ||
    typeof value.status !== "string" ||
    !Number.isSafeInteger(value.attempt_count) ||
    !(typeof value.remote_reference === "string" || value.remote_reference === null) ||
    !(typeof value.last_error_code === "string" || value.last_error_code === null)
  ) {
    throw new Error("invalid DingTalk outbox item");
  }
  return value as DingTalkOutboxItem;
}

export type DingTalkBootstrapResult =
  | { kind: "forbidden"; identity: WorkspaceIdentity }
  | { kind: "ready"; identity: WorkspaceIdentity; data: DingTalkBootstrap };

export async function requestDingTalkBootstrap(): Promise<DingTalkBootstrapResult | null> {
  const identity = await requestIdentity();
  if (identity === null) return null;
  if (!INTERNAL_ROLES.has(identity.user.role)) return { kind: "forbidden", identity };
  const statusResponse = await fetch("/api/integrations/dingtalk/status", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (statusResponse.status === 401) return null;
  if (!statusResponse.ok) throw new Error("DingTalk status unavailable");
  const status = parseStatus(await responseBody(statusResponse));
  let outbox: DingTalkOutboxItem[] | null = null;
  if (["owner", "admin"].includes(identity.user.role)) {
    const outboxResponse = await fetch("/api/integrations/dingtalk/outbox?limit=50", {
      cache: "no-store",
      credentials: "same-origin",
    });
    if (outboxResponse.status === 401) return null;
    const body = await responseBody(outboxResponse);
    if (!outboxResponse.ok || !isRecord(body) || !Array.isArray(body.items)) {
      throw new Error("DingTalk outbox unavailable");
    }
    outbox = body.items.map(parseOutboxItem);
  }
  return { kind: "ready", identity, data: { status, outbox } };
}

export async function startDingTalkLink(): Promise<string | null> {
  const response = await fetch("/api/integrations/dingtalk/oauth/link/start", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ return_path: "/settings/integrations/dingtalk" }),
  });
  if (response.status === 401) return null;
  const body = await responseBody(response);
  if (
    !response.ok ||
    !isRecord(body) ||
    typeof body.authorization_url !== "string"
  ) {
    throw new Error("DingTalk link unavailable");
  }
  const url = new URL(body.authorization_url);
  if (url.protocol !== "https:" || url.hostname !== "login.dingtalk.com") {
    throw new Error("invalid DingTalk authorization host");
  }
  return url.toString();
}
