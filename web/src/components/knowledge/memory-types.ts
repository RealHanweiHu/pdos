export const MEMORY_STATUSES = ["draft", "verified", "archived"] as const;

export type MemoryStatus = (typeof MEMORY_STATUSES)[number];

export type MemoryRecord = {
  id: string;
  project_id: string;
  source_finding_id: string | null;
  source_ncr_id: string | null;
  created_by_user_id: string;
  verified_by_user_id: string | null;
  archived_by_user_id: string | null;
  title: string;
  content: string;
  applicability: string | null;
  tags: string[];
  source_refs: Record<string, unknown>[];
  content_sha256: string;
  status: MemoryStatus;
  verified_at: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
};

export type MemoryDraftInput = {
  title: string;
  content: string;
  applicability: string | null;
  tags: string[];
};

export type KnowledgeSearchItem = {
  memory: MemoryRecord;
  similarity: number;
  embedding_provider: string;
  embedding_model: string;
  href: string;
};
