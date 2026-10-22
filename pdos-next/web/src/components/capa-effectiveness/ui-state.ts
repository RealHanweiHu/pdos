import { proofClockCurrent } from "@/lib/proof-clock";
import {
  uiSchema, tiers, parseModel, same, snapshot, record, uuid, positive, validCommand, validBinding,
  validContext, validRef, validReads, validMissing, json,
  type Context, type VersionRef, type Model, type Operation, type Command, type HostCommand,
  type Binding, type Inputs, type Prepared, type Receipt, type ExpiryTransport, type JsonObject,
} from "./ui-contract";

export type Notice = "none" | "read_failed" | "read_cancelled" | "selection_requires_explicit_choice" |
  "scope_rejected" | "saved" | "saved_read_failed" | "saved_scope_rejected" |
  "not_started" | "blocked" | "invalid_host_material" | "original_request_only" |
  "preview_expired" | "not_saved_expired_proof";
export type Pending = {
  mode: "inputs" | "preview" | "execute" | "expired_preview";
  command: Command; binding: Binding; receipt_subject_type: string; recovery_attempt: boolean;
};
export type UiState = {
  schema_version: typeof uiSchema; context: Context | null; selection: VersionRef | null;
  model: Model | null; draft: JsonObject | null; pending: Pending | null; preview: Prepared | null;
  savedReceipt: Receipt | null; last_outcome: "none" | "not_saved" | "unknown" | "saved";
  completed: { command_id: string; idempotency_key: string; operation: Operation }[];
  read_epoch: number; loading: boolean; read_failed: boolean; notice: Notice;
};
const evolve = (state: UiState, delta: Partial<UiState>): UiState => snapshot({ ...state, ...delta });
const noToken = (command: Command): Command => ({ ...command, payload: Object.fromEntries(
  Object.entries(command.payload).filter(([key]) => !["approval_token", "confirmation_token"].includes(key)),
) });
const tokenField = (operation: Operation) => tiers[operation] === "T2" ? "approval_token" : "confirmation_token";
const unprepared = (command: Command) => !["approval_token", "confirmation_token"].some(key => Object.hasOwn(command.payload, key));
function bindingMatches(state: UiState, binding: Binding): boolean {
  return state.context !== null && state.model?.anchor !== null && state.model?.anchor !== undefined &&
    same(binding.scope, state.context.scope) && binding.caller_id === state.context.caller_id &&
    binding.issue_id === state.model.issue.issue_id && same(binding.issue_ref, state.selection) &&
    binding.capa_id === state.model.anchor.capa_id && binding.purpose === state.model.issue.purpose &&
    same(binding.anchor, state.model.anchor.ref);
}
export function initialState(context: Context, selection: VersionRef | null = null): UiState {
  if (!validContext(context) || (selection !== null && !validRef(selection))) throw new Error("Explicit host scope and fixed selection required");
  return snapshot({ schema_version: uiSchema, context, selection, model: null, draft: null,
    pending: null, preview: null, savedReceipt: null, last_outcome: "none", completed: [],
    read_epoch: 0, loading: false, read_failed: true, notice: "none" });
}
/** Changing Current never changes the explicit historical selection. */
export function selectIssue(state: UiState, selection: VersionRef | null): UiState {
  if (state.pending !== null) return evolve(state, { notice: "original_request_only" });
  if (selection !== null && !validRef(selection)) return evolve(state, { notice: "invalid_host_material" });
  if (same(selection, state.selection)) return state;
  return evolve(state, { selection, model: null, draft: null, preview: null, read_failed: true,
    loading: false, read_epoch: state.read_epoch + 1, notice: "none" });
}
export function setDraft(state: UiState, draft: JsonObject): UiState {
  if (state.pending || state.preview || !record(draft) || !json(draft)) return state;
  // Draft is opaque form state, not professional authority or a generated conclusion.
  return evolve(state, { draft });
}
export function startRead(state: UiState): UiState {
  if (!state.context) return state;
  return evolve(state, { read_epoch: state.read_epoch + 1, loading: true, notice: "none" });
}
export function acceptRead(state: UiState, epoch: number, value: unknown): UiState {
  if (epoch !== state.read_epoch || !state.context) return state;
  const model = parseModel(value);
  if (!model || !same(model.context.scope, state.context.scope) || model.context.caller_id !== state.context.caller_id) return evolve(state, {
    loading: false, read_failed: true, preview: null, notice: "invalid_host_material",
  });
  if (!same(model.issue.ref, state.selection)) return evolve(state, {
    loading: false, read_failed: true, preview: null, notice: "selection_requires_explicit_choice",
  });
  const changed = state.model !== null && !same(state.model, model);
  return evolve(state, { context: model.context, model, loading: false, read_failed: false,
    preview: changed ? null : state.preview, notice: changed && state.preview ? "blocked" : "none" });
}
function clearPrivate(state: UiState): UiState {
  // Only a non-sensitive outcome/notice survives; no receipts, IDs, tokens or private draft.
  return evolve(state, { context: null, selection: null, model: null, draft: null,
    pending: null, preview: null, savedReceipt: null, completed: [],
    read_epoch: state.read_epoch + 1, loading: false, read_failed: true,
    notice: state.last_outcome === "saved" ? "saved_scope_rejected" : "scope_rejected" });
}
export function readFailure(state: UiState, epoch: number, error: { status?: number; code?: string }): UiState {
  if (error.status === 401 || error.status === 403) return clearPrivate(state);
  if (epoch !== state.read_epoch) return state;
  return evolve(state, { loading: false, read_failed: true, preview: null,
    notice: state.last_outcome === "saved" ? "saved_read_failed" :
      error.code === "READ_SUPERSEDED" ? "read_cancelled" : "read_failed" });
}
/** A pure rendering gate. Server capability remains mandatory; this never creates it. */
export function canPrepare(state: UiState, operation: Operation): boolean {
  const m = state.model, ctx = state.context;
  if (!m || !ctx || state.pending || state.preview || state.loading || state.read_failed ||
      !same(m.context, ctx) || !same(m.issue.ref, state.selection) || !same(m.issue.ref, m.current_issue) ||
      m.issue.current_evaluation !== "evaluated_current" || m.issue.source_status !== "current" ||
      m.issue.status !== "awaiting_verification" || !m.anchor || m.anchor.source_status !== "current") return false;
  const cap = m.operations[operation];
  if (!cap || cap.allowed !== true || cap.current_evaluation !== "evaluated_current" ||
      cap.authority.authorized !== true || cap.authority.qualified !== true || !bindingMatches(state, cap.binding)) return false;
  if (m.issue.visibility === "private" && m.issue.owner_id !== ctx.caller_id) return false;
  const independent = tiers[operation] === "T2";
  if (independent && (m.anchor.visibility !== "category" || cap.independence !== "verified")) return false;
  if (operation === "quality.capa.effectiveness.decide" && m.effectiveness !== null) return false;
  if (operation === "quality.issue.close" && (!m.effectiveness || m.effectiveness.outcome !== "effective" ||
      m.effectiveness.actor_id !== ctx.caller_id || !same(m.effectiveness.issue_ref, m.current_issue))) return false;
  return true;
}
export function begin(state: UiState, value: HostCommand): UiState {
  if (state.pending) return evolve(state, { notice: "original_request_only" });
  if (value.schema_version !== uiSchema || !validContext(value.context) || !validBinding(value.binding) ||
      !validCommand(value.command) || !unprepared(value.command) || !same(value.context, state.context) ||
      !canPrepare(state, value.command.operation) || !bindingMatches(state, value.binding)) return evolve(state, { notice: "blocked" });
  const cap = state.model!.operations[value.command.operation];
  if (!same(cap.binding, value.binding) || !same(value.command.source_read_set, cap.required_source_read_set) ||
      value.command.product_id !== state.context!.scope.product_id || value.command.expected_revision !== state.context!.product_revision ||
      state.completed.some(done => done.command_id === value.command.command_id || done.idempotency_key === value.command.idempotency_key))
    return evolve(state, { notice: "invalid_host_material" });
  return evolve(state, { pending: { mode: "inputs", command: value.command, binding: value.binding,
    receipt_subject_type: cap.receipt_subject_type, recovery_attempt: false }, preview: null,
    savedReceipt: null, last_outcome: "not_saved", loading: false,
    read_epoch: state.read_epoch + 1, notice: "none" });
}
export function acceptInputs(state: UiState, value: Inputs): UiState {
  const p = state.pending;
  if (!p || p.mode !== "inputs") return state;
  if (value.schema_version !== uiSchema || !validCommand(value.command) || !validBinding(value.binding) ||
      !same(value.command, p.command) || !same(value.binding, p.binding) || typeof value.allowed !== "boolean" ||
      !validMissing(value.missing) || !validReads(value.required_source_read_set) ||
      !same(value.required_source_read_set, p.command.source_read_set)) return evolve(state, { notice: "invalid_host_material" });
  if (!value.allowed) return evolve(state, { pending: null, preview: null, notice: "blocked", last_outcome: "not_saved" });
  return evolve(state, { pending: { ...p, mode: "preview" }, notice: "none" });
}
export function acceptPreview(state: UiState, value: Prepared, now: number): UiState {
  const p = state.pending;
  if (!p || p.mode !== "preview") return state;
  const field = tokenField(p.command.operation), other = field === "approval_token" ? "confirmation_token" : "approval_token";
  if (value.schema_version !== uiSchema || !validCommand(value.command) || !validBinding(value.binding) ||
      !same(noToken(value.command), p.command) || !same(value.binding, p.binding) ||
      typeof value.command.payload[field] !== "string" || String(value.command.payload[field]).length < 20 ||
      Object.hasOwn(value.command.payload, other) || value.write_tier !== tiers[p.command.operation] ||
      value.named_decision !== (tiers[p.command.operation] === "T2") || !proofClockCurrent(tiers[p.command.operation], value.expires_at, now) ||
      !record(value.review) || !Object.hasOwn(value.review, "before") || !Object.hasOwn(value.review, "after") ||
      !json(value.review.before) || !json(value.review.after) ||
      typeof value.review.effect !== "string" || !value.review.effect.trim()) return evolve(state, { notice: "invalid_host_material" });
  return evolve(state, { preview: value, notice: "none" });
}
export function confirm(state: UiState, now: number): UiState {
  const p = state.pending, prepared = state.preview;
  if (!p || p.mode !== "preview" || !prepared) return state;
  if (!proofClockCurrent(tiers[p.command.operation], prepared.expires_at, now)) return evolve(state, {
    preview: null, pending: { ...p, mode: "expired_preview" }, notice: "preview_expired",
  });
  // Re-evaluate the stored host scope, without dropping the unresolved request to pass canPrepare.
  if (!canPrepare(evolve(state, { pending: null, preview: null }), p.command.operation) ||
      !bindingMatches(state, p.binding) || p.command.expected_revision !== state.context?.product_revision ||
      !same(p.command.source_read_set, state.model?.operations[p.command.operation].required_source_read_set))
    return evolve(state, { preview: null, notice: "blocked" });
  return evolve(state, { pending: { ...p, mode: "execute", command: prepared.command, recovery_attempt: false },
    preview: null, last_outcome: "unknown", notice: "none", loading: false, read_epoch: state.read_epoch + 1 });
}
export function requestFailure(state: UiState, error: { status?: number; code?: string }): UiState {
  if (error.status === 401 || error.status === 403) return clearPrivate(state);
  if (state.last_outcome === "saved") return evolve(state, { read_failed: true, loading: false, notice: "saved_read_failed" });
  const p = state.pending;
  return evolve(state, { preview: null, loading: false,
    last_outcome: p?.mode === "execute" ? "unknown" : "not_saved",
    notice: p?.mode === "execute" ? "original_request_only" : "not_started" });
}
/** Only repeats an existing mode; never manufactures an ID, token, time or new payload. */
export function resumeOriginal(state: UiState): UiState {
  if (!state.context || !state.pending || state.savedReceipt || state.pending.mode === "expired_preview") return state;
  return evolve(state, { pending: { ...state.pending, recovery_attempt: state.pending.mode === "execute" }, notice: "none" });
}
/** Host absence proof must be mapped from a separately frozen real transport protocol. */
export function acceptExpiredUnsaved(state: UiState, recoveredFailure: unknown, transport: ExpiryTransport | null = null): UiState {
  const p = state.pending;
  if (!transport || !p || p.mode !== "execute" || !p.recovery_attempt || state.savedReceipt || state.last_outcome === "saved") return state;
  let value;
  try { value = transport.inspect(p.command, recoveredFailure); } catch { return state; }
  if (!record(value) || Object.keys(value).length !== 3 || value.schema_version !== uiSchema ||
      value.state !== "not_saved_expired_proof" || !validCommand(value.command) ||
      !unprepared(value.command) || !same(value.command, noToken(p.command))) return state;
  return evolve(state, { pending: { ...p, mode: "expired_preview", command: value.command, recovery_attempt: false },
    preview: null, last_outcome: "not_saved", notice: "not_saved_expired_proof" });
}
export function requestRepreview(state: UiState): UiState {
  if (!state.context || state.pending?.mode !== "expired_preview") return state;
  return evolve(state, { pending: { ...state.pending, mode: "preview", recovery_attempt: false }, notice: "none" });
}
/** Explicit cancellation before execute is known not to have submitted a write. */
export function cancelPreparation(state: UiState): UiState {
  if (state.pending?.mode === "execute") return evolve(state, { notice: "original_request_only" });
  return evolve(state, { pending: null, preview: null, notice: "none" });
}
export function acceptReceipt(state: UiState, receipt: Receipt): UiState {
  const p = state.pending;
  if (!p || p.mode !== "execute") return state;
  if (!uuid(receipt.id) || receipt.operation !== p.command.operation || !uuid(receipt.subject_id) ||
      !positive(receipt.subject_revision) || receipt.subject_type !== p.receipt_subject_type)
    return requestFailure(state, {});
  return evolve(state, { savedReceipt: receipt, pending: null, preview: null, draft: null,
    last_outcome: "saved", read_failed: true, loading: false, read_epoch: state.read_epoch + 1, notice: "saved",
    completed: [...state.completed, { command_id: p.command.command_id, idempotency_key: p.command.idempotency_key, operation: p.command.operation }] });
}
export function outcomeLabel(value: "effective" | "ineffective" | "unknown" | "indeterminate"): string {
  return { effective: "已具名决定有效", ineffective: "已具名决定无效，继续待验证",
    unknown: "未知，不能替代有效性决定", indeterminate: "尚不能确定，保留验证缺项" }[value];
}
