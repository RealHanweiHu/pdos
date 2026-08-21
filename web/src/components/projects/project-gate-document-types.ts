export type GateReadinessBlocker = { key: string; kind: string; label: string };

export type ProjectGate = {
  id: string;
  project_id: string;
  stage: { id: string; code: string; name: string; sequence: number };
  code: string;
  name: string;
  status: string;
  is_current: boolean;
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
    signoffs: { slot: string; requirement: string; status: string }[];
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
  extraction_status: "extracted" | "ocr_required";
  created_at: string;
};
