export type ReconciliationRequest = { run_id: string; root: string; expected_cancel_epoch: number };
export type ReconciliationRecord = {
  event_id: string; mode: "automatic" | "administrator"; closed_at: string;
  original_cancel_epoch: number; business_receipt_count: number; recovered_call_count: number;
  failed_call_count: number; held_tokens: number; estimated_micro_usd: number;
  may_start_new_request: boolean; external_effect_unknown: boolean;
};
export type ReconciliationReading = {
  run_id: string; status: string; cancel_epoch: number; required: boolean; can_finalize: boolean;
  automatic_after: string | null; counts: { calls: number; pending_calls: number; business_receipts: number };
  held_tokens: number; estimated_micro_usd: number; completed: ReconciliationRecord | null;
  calls: { id: string; tool: string; state: string; receipt_id: string | null; charged_tokens: number; held_tokens: number; cost_state: string }[];
  receipts: { id: string; operation: string; subject_type: string; subject_id: string; subject_revision: number }[];
  next_call_cursor: string | null; next_receipt_cursor: string | null;
};

/** Only the original technical request is restored; no actor, result or receipt is supplied. */
export function restoreReconciliation(value: unknown, runId: string, root: string): ReconciliationRequest | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (Object.keys(item).some(key => !["run_id", "root", "expected_cancel_epoch"].includes(key)) || item.run_id !== runId || item.root !== root || !Number.isSafeInteger(item.expected_cancel_epoch) || Number(item.expected_cancel_epoch) < 0) return null;
  return item as ReconciliationRequest;
}

export function reconciliationNeeded(run: { status: string; error_code?: string | null }): boolean {
  return run.status === "waiting_input" && run.error_code === "EXTERNAL_OUTCOME_UNKNOWN";
}
