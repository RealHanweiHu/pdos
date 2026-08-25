import type { ProjectDocument, ProjectGate } from "./project-gate-document-types";
import { isRecord } from "@/components/workspace-api";

async function json(response: Response) {
  if (!response.ok) throw new Error("项目数据暂不可用");
  return response.json() as Promise<unknown>;
}

export function isGate(value: unknown): value is ProjectGate {
  return isRecord(value) && typeof value.id === "string" && typeof value.status === "string" &&
    typeof value.is_current === "boolean" && isRecord(value.stage) &&
    typeof value.stage.id === "string" && typeof value.stage.code === "string" &&
    typeof value.stage.name === "string" && Number.isInteger(value.stage.sequence) &&
    isRecord(value.readiness) && typeof value.readiness.ready === "boolean" &&
    Array.isArray(value.readiness.blocker_keys) &&
    value.readiness.blocker_keys.every((key) => typeof key === "string") &&
    Array.isArray(value.readiness.blockers) && value.readiness.blockers.every((blocker) =>
      isRecord(blocker) && typeof blocker.key === "string" &&
      typeof blocker.kind === "string" && typeof blocker.label === "string");
}

function isDocument(value: unknown): value is ProjectDocument {
  return isRecord(value) && typeof value.document_id === "string" &&
    typeof value.project_id === "string" && typeof value.filename === "string" &&
    typeof value.media_type === "string" && typeof value.classification === "string" &&
    typeof value.size_bytes === "number" && typeof value.sha256 === "string" &&
    (value.extraction_status === "extracted" || value.extraction_status === "ocr_required") &&
    typeof value.created_at === "string";
}

export async function requestProjectGates(projectId: string): Promise<ProjectGate[]> {
  const body = await json(
    await fetch(`/api/projects/${encodeURIComponent(projectId)}/gates`, {
      credentials: "same-origin",
      cache: "no-store",
    }),
  );
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(isGate)) {
    throw new Error("Gate 响应无效");
  }
  return body.items;
}

export async function openProjectGateRound(
  projectId: string,
  gateId: string,
): Promise<ProjectGate> {
  const body = await json(
    await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/gates/${encodeURIComponent(gateId)}/rounds`,
      { method: "POST", credentials: "same-origin" },
    ),
  );
  if (!isGate(body)) throw new Error("Gate 响应无效");
  return body;
}

export async function signProjectGateRound(
  projectId: string,
  gateId: string,
  roundId: string,
  slot: "product" | "engineering" | "quality",
): Promise<ProjectGate> {
  const body = await json(
    await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/gates/${encodeURIComponent(gateId)}/rounds/${encodeURIComponent(roundId)}/signoffs/${slot}`,
      {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "approved", note: null }),
      },
    ),
  );
  if (!isGate(body)) throw new Error("Gate 响应无效");
  return body;
}

export async function requestProjectDocuments(projectId: string): Promise<ProjectDocument[]> {
  const body = await json(
    await fetch(`/api/projects/${encodeURIComponent(projectId)}/documents`, {
      credentials: "same-origin",
      cache: "no-store",
    }),
  );
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(isDocument)) {
    throw new Error("文档响应无效");
  }
  return body.items;
}

export async function uploadProjectDocument(
  projectId: string,
  file: File,
  classification: string,
): Promise<ProjectDocument> {
  const form = new FormData();
  form.set("project_id", projectId);
  form.set("classification", classification);
  form.set("file", file);
  const body = await json(
    await fetch(`/api/projects/${encodeURIComponent(projectId)}/documents`, {
      method: "POST",
      credentials: "same-origin",
      body: form,
    }),
  );
  const normalized = isRecord(body) ? { ...body, created_at: new Date().toISOString() } : body;
  if (!isDocument(normalized)) {
    throw new Error("文档响应无效");
  }
  return normalized;
}
