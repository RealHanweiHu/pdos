export type NamedSignerPolicy = { required_slots?: string[]; source?: { project_template_version_id: string; template_id: string; template_version: number; template_digest: string } };

export type GateAssignment = {
  required_policy?: NamedSignerPolicy;
  request_id: string; request_digest: string; replaces_round_id: string | null; reason: string;
  signers: Record<string, { user_id: string; display_name: string; role: string }>;
};

export type GateReadinessBlocker = { key: string; kind: string; label: string };

export type ProjectGate = {
  id: string;
  project_id: string;
  stage: { id: string; code: string; name: string; sequence: number };
  code: string;
  name: string;
  status: string;
  is_current: boolean;
  signing_basis?: string;
  named_signer_policy?: NamedSignerPolicy;
  readiness: {
    ready: boolean;
    blocker_keys: string[];
    blockers: GateReadinessBlocker[];
    evaluated_at: string;
  };
  round: {
    id: string;
    round_number: number;
    status: string;
    routing_snapshot?: { assignment?: GateAssignment; dependencies?: Record<string, string[]>; source?: { template_id: string; template_version: number; template_digest: string; project_template_version_id: string } };
    routing_blockers?: Record<string, string[]>;
    readiness_snapshot?: { ready?: boolean; evaluated_at?: string } | null;
    signoffs: { id?: string; slot: string; requirement: string; status: string; signed_by_user_id?: string | null; signed_at?: string | null; note?: string | null }[];
  } | null;
};

export type ProjectDocument = {
  document_id: string;
  project_id: string;
  filename: string;
  media_type: string;
  classification: string;
  size_bytes: number;
  sha256: string;
  extraction_status: "extracted" | "ocr_required" | "preview_only";
  created_at: string;
};
