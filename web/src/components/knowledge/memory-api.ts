import { parseKnowledgeKind, type KnowledgeKind } from "./knowledge-kind";
import type { SourceSelection } from "./source-picker";
import { isSafePdosHref } from "@/components/ai/ai-api";
import { isRecord, responseBody } from "@/components/workspace-api";

import {
  MEMORY_STATUSES,
  type KnowledgeSearchItem,
  type MemoryDraftInput,
  type MemoryRecord,
  type MemoryStatus,
} from "./memory-types";

function isNullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

export function parseMemory(value: unknown): MemoryRecord {
  if (
    !isRecord(value) ||
    ![
      "id",
      "project_id",
      "created_by_user_id",
      "title",
      "content",
      "content_sha256",
      "created_at",
      "updated_at",
    ].every((key) => typeof value[key] === "string") ||
    ![
      "source_finding_id",
      "source_ncr_id",
      "verified_by_user_id",
      "archived_by_user_id",
      "applicability",
      "verified_at",
      "archived_at",
    ].every((key) => isNullableString(value[key])) ||
    (value.review_digest !== undefined && (typeof value.review_digest !== "string" || !/^[0-9a-f]{64}$/.test(value.review_digest))) ||
    (value.last_edited_by_user_id !== undefined && !isNullableString(value.last_edited_by_user_id)) ||
    !MEMORY_STATUSES.includes(value.status as MemoryStatus) ||
    !Array.isArray(value.tags) ||
    !value.tags.every((tag) => typeof tag === "string") ||
    !Array.isArray(value.source_refs) ||
    !value.source_refs.every(isRecord)
  ) {
    throw new Error("invalid Memory response");
  }
  return { ...value, knowledge_kind: parseKnowledgeKind(value.knowledge_kind) } as MemoryRecord;
}

async function requireOk(response: Response, fallback: string): Promise<unknown> {
  if (!response.ok) {
    const body = await responseBody(response).catch(() => null);
    const detail = isRecord(body) && isRecord(body.detail) ? body.detail : null;
    throw new Error(detail && typeof detail.message === "string" ? detail.message : fallback);
  }
  return responseBody(response);
}

export async function requestMemories(projectId: string): Promise<MemoryRecord[]> {
  const body = await requireOk(
    await fetch(`/api/projects/${encodeURIComponent(projectId)}/memories`, {
      cache: "no-store",
      credentials: "same-origin",
    }),
    "Memory 历史暂不可用",
  );
  if (!isRecord(body) || !Array.isArray(body.items)) throw new Error("invalid Memory list");
  return body.items.map(parseMemory);
}

export async function createMemory(
  projectId: string,
  input: MemoryDraftInput & { source_selections?: SourceSelection[] },
): Promise<MemoryRecord> {
  return mutateMemory(`/api/projects/${encodeURIComponent(projectId)}/memories`, "POST", input);
}

export async function editMemory(
  projectId: string,
  memoryId: string,
  input: MemoryDraftInput & { expected_review_digest: string; source_selections?: SourceSelection[] | null },
): Promise<MemoryRecord> {
  return mutateMemory(
    `/api/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryId)}`,
    "PATCH",
    input,
  );
}

export async function transitionMemory(
  projectId: string,
  memoryId: string,
  action: "verify" | "archive" | "reembed",
  reviewDigest?: string,
): Promise<MemoryRecord> {
  if (action === "verify" && !reviewDigest) throw new Error("请刷新获取当前审核版本");
  return mutateMemory(
    `/api/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryId)}/${action}`,
    "POST",
    action === "verify" ? { expected_review_digest: reviewDigest } : undefined,
  );
}

async function mutateMemory(
  path: string,
  method: "POST" | "PATCH",
  input?: object,
) {
  const body = await requireOk(
    await fetch(path, {
      method,
      cache: "no-store",
      credentials: "same-origin",
      headers: input ? { "Content-Type": "application/json" } : undefined,
      body: input ? JSON.stringify(input) : undefined,
    }),
    "Memory 操作失败",
  );
  return parseMemory(body);
}

export async function searchKnowledge(
  projectId: string,
  query: string,
  knowledgeKind: KnowledgeKind | "unclassified" | null = null,
): Promise<KnowledgeSearchItem[]> {
  const body = await requireOk(
    await fetch("/api/knowledge/search", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, query, limit: 10, knowledge_kind: knowledgeKind }),
    }),
    "语义检索暂不可用",
  );
  if (!isRecord(body) || body.source_status !== "ready" || !Array.isArray(body.items)) {
    throw new Error("invalid Knowledge Search response");
  }
  return body.items.map((item) => {
    if (
      !isRecord(item) ||
      typeof item.similarity !== "number" ||
      !Number.isFinite(item.similarity) ||
      typeof item.embedding_provider !== "string" ||
      typeof item.embedding_model !== "string" ||
      !isSafePdosHref(item.href)
    ) {
      throw new Error("invalid Knowledge Search item");
    }
    return {
      memory: parseMemory(item.memory),
      similarity: item.similarity,
      embedding_provider: item.embedding_provider,
      embedding_model: item.embedding_model,
      href: item.href,
    };
  });
}
