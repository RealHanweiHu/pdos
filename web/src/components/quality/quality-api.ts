import { isRecord } from "@/components/workspace-api";

import type {
  Complaint,
  ComplaintCreateInput,
  Ncr,
  NcrCreateInput,
  NcrDetail,
} from "./quality-types";

function isComplaint(value: unknown): value is Complaint {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.code === "string" &&
    typeof value.project_id === "string" &&
    typeof value.title === "string" &&
    typeof value.description === "string" &&
    typeof value.status === "string" &&
    typeof value.severity === "string" &&
    typeof value.source === "string" &&
    typeof value.owner_user_id === "string" &&
    typeof value.occurred_at === "string" &&
    typeof value.reported_at === "string" &&
    Array.isArray(value.document_refs)
  );
}

function isNcr(value: unknown): value is Ncr {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.code === "string" &&
    typeof value.complaint_id === "string" &&
    typeof value.status === "string" &&
    typeof value.nonconformity === "string" &&
    typeof value.target_date === "string"
  );
}

async function body(response: Response): Promise<unknown> {
  const parsed = (await response.json()) as unknown;
  if (!response.ok) {
    const detail = isRecord(parsed) && isRecord(parsed.detail) ? parsed.detail : null;
    throw new Error(
      detail && typeof detail.message === "string" ? detail.message : "质量记录操作失败",
    );
  }
  return parsed;
}

async function qualityFetch(projectId: string, path: string, init?: RequestInit) {
  return fetch(`/api/projects/${encodeURIComponent(projectId)}/quality/${path}`, {
    ...init,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
}

export async function requestComplaints(projectId: string): Promise<Complaint[]> {
  const parsed = await body(await qualityFetch(projectId, "complaints"));
  if (!isRecord(parsed) || !Array.isArray(parsed.items) || !parsed.items.every(isComplaint)) {
    throw new Error("Complaint 响应无效");
  }
  return parsed.items;
}

export async function createComplaint(projectId: string, input: ComplaintCreateInput) {
  const parsed = await body(
    await qualityFetch(projectId, "complaints", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
  if (!isComplaint(parsed)) throw new Error("Complaint 响应无效");
  return parsed;
}

export async function triageComplaint(
  projectId: string,
  complaintId: string,
  input: NcrCreateInput,
) {
  const parsed = await body(
    await qualityFetch(projectId, `complaints/${encodeURIComponent(complaintId)}/triage`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
  if (
    !isRecord(parsed) ||
    !isComplaint(parsed.complaint) ||
    !isNcr(parsed.ncr)
  ) {
    throw new Error("Complaint triage 响应无效");
  }
  return { complaint: parsed.complaint, ncr: parsed.ncr };
}

export async function requestNcrs(projectId: string, complaintId: string): Promise<Ncr[]> {
  const parsed = await body(
    await qualityFetch(projectId, `complaints/${encodeURIComponent(complaintId)}/ncrs`),
  );
  if (!isRecord(parsed) || !Array.isArray(parsed.items) || !parsed.items.every(isNcr)) {
    throw new Error("NCR 响应无效");
  }
  return parsed.items;
}

export async function requestNcrDetail(projectId: string, ncrId: string): Promise<NcrDetail> {
  const parsed = await body(
    await qualityFetch(projectId, `ncrs/${encodeURIComponent(ncrId)}/detail`),
  );
  if (
    !isRecord(parsed) ||
    !isNcr(parsed.ncr) ||
    !Array.isArray(parsed.root_causes) ||
    !Array.isArray(parsed.actions) ||
    !Array.isArray(parsed.effectiveness_reviews)
  ) {
    throw new Error("CAPA 详情响应无效");
  }
  return parsed as NcrDetail;
}
