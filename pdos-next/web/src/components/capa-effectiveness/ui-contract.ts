/** Staged host-to-UI contract. This is neither a public API nor a write payload schema. */
export const uiSchema = "capa-effectiveness-ui.v1" as const;
export const operations = [
  "quality.capa.verification.candidate.record",
  "quality.capa.observation.record",
  "quality.capa.verification.review",
  "quality.capa.effectiveness.decide",
  "quality.issue.close",
] as const;
export type Operation = (typeof operations)[number];
export type Tier = "T1" | "T2";
export const tiers: Readonly<Record<Operation, Tier>> = {
  "quality.capa.verification.candidate.record": "T1",
  "quality.capa.observation.record": "T1",
  "quality.capa.verification.review": "T2",
  "quality.capa.effectiveness.decide": "T2",
  "quality.issue.close": "T2",
};
export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type JsonObject = { [key: string]: Json };
export type Scope = { tenant_id: string; product_id: string; project_id: string };
export type Context = { scope: Scope; caller_id: string; product_revision: number };
export type VersionRef = { id: string; revision: number };
export type MaterialRef = VersionRef & { sha256: string };
export type Read = { artifact_id: string; expected_revision: number };
export type Missing = { code: string; detail: string };
export type Evaluation = "evaluated_current" | "not_evaluated_historical" | "unavailable";
export type SourceState = "current" | "needs_recheck" | "unavailable";
export type Authority = { authorized: boolean; qualified: boolean | null; synthetic: boolean };
export type Binding = {
  scope: Scope; caller_id: string; issue_id: string; issue_ref: VersionRef;
  capa_id: string; purpose: string; anchor: MaterialRef;
};
export type Capability = {
  operation: Operation; binding: Binding; allowed: boolean; authority: Authority;
  independence: "verified" | "not_verified" | "not_required";
  current_evaluation: Evaluation; missing: Missing[];
  required_source_read_set: Read[]; receipt_subject_type: string;
};
export type Issue = {
  issue_id: string; ref: VersionRef; owner_id: string; visibility: "private" | "category" | "audience";
  purpose: string; status: "actioning" | "awaiting_verification" | "closed";
  current_evaluation: Evaluation; source_status: SourceState;
};
export type Anchor = {
  ref: MaterialRef; origin_issue: VersionRef; issue_id: string; capa_id: string;
  scope: Scope; owner_id: string; visibility: "private" | "category" | "audience";
  purpose: string; nature: "real" | "synthetic"; source_status: SourceState;
};
export type LateLink = {
  ref: MaterialRef; issue_id: string; meaning: "planned" | "performed";
  formal: VersionRef; run: VersionRef | null; current_evaluation: Evaluation;
  source_status: SourceState; missing: Missing[];
};
export type Candidate = {
  ref: MaterialRef; anchor: MaterialRef; late_link: MaterialRef;
  applicable: null; independently_verified: null; observation_complete: null;
  result: "indeterminate"; current_evaluation: Evaluation; source_status: SourceState;
  missing: Missing[];
};
export type RulePublication = {
  ref: MaterialRef; publication: "host_only"; issuer_key: string; issuer_version: string;
  issuer_epoch: number; nature: "real" | "synthetic"; source_status: SourceState;
  current_evaluation: Evaluation; valid_from: string; valid_until: string; missing: Missing[];
};
export type Observation = {
  ref: MaterialRef; rule: MaterialRef; observed_from: string; observed_until: string;
  occurred_at: string; original_timezone: string; current_evaluation: Evaluation;
  source_status: SourceState; missing: Missing[];
};
export type Review = {
  ref: MaterialRef; candidate: MaterialRef; rule: MaterialRef; observations: MaterialRef[];
  reviewer_id: string; conclusion: "applicable" | "not_applicable" | "unknown";
  occurred_at: string; original_timezone: string; current_evaluation: Evaluation;
  source_status: SourceState; missing: Missing[];
};
export type Effectiveness = {
  issue_ref: VersionRef; actor_id: string; outcome: "effective" | "ineffective";
};
export type Model = {
  schema_version: typeof uiSchema; context: Context; issue: Issue; current_issue: VersionRef | null;
  anchor: Anchor | null; late_links: LateLink[]; candidates: Candidate[];
  rule_publications: RulePublication[]; observations: Observation[]; reviews: Review[];
  effectiveness: Effectiveness | null;
  operations: Record<Operation, Capability>; missing: Missing[];
};
/** The host supplies complete validated material; this package does not construct payloads. */
export type Command = {
  command_id: string; idempotency_key: string; product_id: string; expected_revision: number;
  operation: Operation; payload: JsonObject; source_read_set: Read[];
};
export type HostCommand = { schema_version: typeof uiSchema; context: Context; binding: Binding; command: Command };
export type Inputs = {
  schema_version: typeof uiSchema; command: Command; binding: Binding;
  allowed: boolean; required_source_read_set: Read[]; missing: Missing[];
};
export type Prepared = {
  schema_version: typeof uiSchema; command: Command; binding: Binding;
  expires_at: string | null; write_tier: Tier; named_decision: boolean;
  review: { before: Json; after: Json; effect: string };
};
export type Receipt = {
  id: string; operation: Operation; subject_id: string; subject_revision: number; subject_type: string;
};
/** Internal trusted transport result, not a new HTTP code/route or proof of absence by itself. */
export type ExpiredUnsaved = {
  schema_version: typeof uiSchema; state: "not_saved_expired_proof"; command: Command;
};
/** Configured only after Root freezes a real response protocol for these operations. */
export type ExpiryTransport = {
  inspect: (original: Command, recoveredFailure: unknown) => ExpiredUnsaved | null;
};

export const record = (x: unknown): x is Record<string, unknown> =>
  x !== null && typeof x === "object" && !Array.isArray(x) &&
  [Object.prototype, null].includes(Object.getPrototypeOf(x));
export const uuid = (x: unknown): x is string => typeof x === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(x);
export const positive = (x: unknown): x is number => Number.isSafeInteger(x) && Number(x) > 0;
const text = (x: unknown): x is string => typeof x === "string" && x.length > 0;
const hasKeys = (x: Record<string, unknown>, keys: string[]) =>
  Object.keys(x).length === keys.length && keys.every(key => Object.hasOwn(x, key));
export const validRef = (x: unknown): x is VersionRef => record(x) &&
  hasKeys(x, ["id", "revision"]) && uuid(x.id) && positive(x.revision);
export const validMaterial = (x: unknown): x is MaterialRef => record(x) &&
  hasKeys(x, ["id", "revision", "sha256"]) && uuid(x.id) && positive(x.revision) &&
  typeof x.sha256 === "string" && /^[0-9a-f]{64}$/.test(x.sha256);
export const validScope = (x: unknown): x is Scope => record(x) &&
  hasKeys(x, ["tenant_id", "product_id", "project_id"]) && Object.values(x).every(uuid);
export const validContext = (x: unknown): x is Context => record(x) &&
  hasKeys(x, ["scope", "caller_id", "product_revision"]) && validScope(x.scope) &&
  uuid(x.caller_id) && positive(x.product_revision);
export function same(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => same(v, b[i]));
  if (!record(a) || !record(b)) return false;
  const keys = Object.keys(a); return keys.length === Object.keys(b).length &&
    keys.every(key => Object.hasOwn(b, key) && same(a[key], b[key]));
}
export function json(x: unknown, depth = 0, seen = new Set<object>()): x is Json {
  if (depth > 40) return false;
  if (x === null || typeof x === "boolean" || typeof x === "string") return true;
  if (typeof x === "number") return Number.isFinite(x);
  if (!Array.isArray(x) && !record(x)) return false;
  if (seen.has(x)) return false; seen.add(x);
  const values = Array.isArray(x) ? x : Object.values(x);
  const result = values.every(v => json(v, depth + 1, seen));
  seen.delete(x); return result;
}
/** Clone/freeze without serializing clocks, decimal strings or negative-zero JSON numbers. */
export function snapshot<T>(x: T): T {
  if (Array.isArray(x)) return Object.freeze(x.map(snapshot)) as T;
  if (record(x)) return Object.freeze(Object.fromEntries(Object.entries(x).map(([k, v]) => [k, snapshot(v)]))) as T;
  return x;
}
export function validReads(x: unknown): x is Read[] {
  if (!Array.isArray(x)) return false;
  const seen = new Set<string>();
  return x.every(v => {
    if (!record(v) || !hasKeys(v, ["artifact_id", "expected_revision"]) || !uuid(v.artifact_id) ||
        !positive(v.expected_revision) || seen.has(v.artifact_id)) return false;
    seen.add(v.artifact_id); return true;
  });
}
export function validMissing(x: unknown): x is Missing[] {
  return Array.isArray(x) && x.every(v => record(v) &&
    hasKeys(v, ["code", "detail"]) && text(v.code) && text(v.detail));
}
/** Validation only; returns original aware ISO string, including fractional precision and offset. */
export function eventTime(x: unknown): string | null {
  return typeof x === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(x) &&
    Number.isFinite(Date.parse(x)) ? x : null;
}
export function eventTimezone(x: unknown): string | null {
  if (typeof x !== "string" || !x || x !== x.trim() || /^[+-]/.test(x)) return null;
  try { new Intl.DateTimeFormat("en", { timeZone: x }); return x; } catch { return null; }
}
export const validBinding = (x: unknown): x is Binding => record(x) &&
  hasKeys(x, ["scope", "caller_id", "issue_id", "issue_ref", "capa_id", "purpose", "anchor"]) &&
  validScope(x.scope) && uuid(x.caller_id) && uuid(x.issue_id) && validRef(x.issue_ref) &&
  uuid(x.capa_id) && text(x.purpose) && x.purpose === x.purpose.trim() && validMaterial(x.anchor);
export function validCommand(x: unknown): x is Command {
  return record(x) && hasKeys(x, ["command_id", "idempotency_key", "product_id", "expected_revision", "operation", "payload", "source_read_set"]) &&
    uuid(x.command_id) && uuid(x.idempotency_key) && uuid(x.product_id) && positive(x.expected_revision) &&
    operations.includes(x.operation as Operation) && record(x.payload) && json(x.payload) && validReads(x.source_read_set);
}
const evaluation = (x: unknown): x is Evaluation => ["evaluated_current", "not_evaluated_historical", "unavailable"].includes(String(x));
const sourceState = (x: unknown): x is SourceState => ["current", "needs_recheck", "unavailable"].includes(String(x));
const materialRow = (x: unknown): x is Record<string, unknown> => record(x) &&
  validMaterial(x.ref) && evaluation(x.current_evaluation) && sourceState(x.source_status) && validMissing(x.missing);
const authority = (x: unknown): x is Authority => record(x) && hasKeys(x, ["authorized", "qualified", "synthetic"]) &&
  typeof x.authorized === "boolean" && (x.qualified === null || typeof x.qualified === "boolean") && typeof x.synthetic === "boolean";
export function validCapability(x: unknown): x is Capability {
  return record(x) && hasKeys(x, ["operation", "binding", "allowed", "authority", "independence", "current_evaluation", "missing", "required_source_read_set", "receipt_subject_type"]) &&
    operations.includes(x.operation as Operation) && validBinding(x.binding) && typeof x.allowed === "boolean" && authority(x.authority) &&
    ["verified", "not_verified", "not_required"].includes(String(x.independence)) && evaluation(x.current_evaluation) &&
    validMissing(x.missing) && validReads(x.required_source_read_set) && text(x.receipt_subject_type);
}
/** Strict known version. No capability, NULL or current-pointer defaults. */
export function parseModel(x: unknown): Model | null {
  if (!record(x) || !hasKeys(x, ["schema_version", "context", "issue", "current_issue", "anchor", "late_links", "candidates", "rule_publications", "observations", "reviews", "effectiveness", "operations", "missing"]) ||
      x.schema_version !== uiSchema || !validContext(x.context) || !record(x.issue) || !validMissing(x.missing)) return null;
  const issue = x.issue;
  if (!hasKeys(issue, ["issue_id", "ref", "owner_id", "visibility", "purpose", "status", "current_evaluation", "source_status"]) ||
      !uuid(issue.issue_id) || !validRef(issue.ref) || !uuid(issue.owner_id) || !["private", "category", "audience"].includes(String(issue.visibility)) ||
      !text(issue.purpose) || issue.purpose !== issue.purpose.trim() || !["actioning", "awaiting_verification", "closed"].includes(String(issue.status)) ||
      !evaluation(issue.current_evaluation) || !sourceState(issue.source_status) || (x.current_issue !== null && !validRef(x.current_issue))) return null;
  if (x.anchor !== null) {
    const a = x.anchor;
    if (!record(a) || !hasKeys(a, ["ref", "origin_issue", "issue_id", "capa_id", "scope", "owner_id", "visibility", "purpose", "nature", "source_status"]) ||
        !validMaterial(a.ref) || !validRef(a.origin_issue) || a.issue_id !== issue.issue_id || !uuid(a.capa_id) || !same(a.scope, x.context.scope) ||
        a.owner_id !== issue.owner_id || a.visibility !== issue.visibility || a.purpose !== issue.purpose ||
        !["real", "synthetic"].includes(String(a.nature)) || !sourceState(a.source_status)) return null;
  }
  if (!record(x.operations) || !hasKeys(x.operations, [...operations])) return null;
  for (const operation of operations) {
    const cap = x.operations[operation];
    if (!validCapability(cap) || cap.operation !== operation || !same(cap.binding.scope, x.context.scope) ||
        cap.binding.caller_id !== x.context.caller_id || cap.binding.issue_id !== issue.issue_id ||
        !same(cap.binding.issue_ref, issue.ref) || cap.binding.purpose !== issue.purpose ||
        (x.anchor !== null && (!same(cap.binding.anchor, (x.anchor as Anchor).ref) || cap.binding.capa_id !== (x.anchor as Anchor).capa_id)) ||
        (["quality.capa.effectiveness.decide", "quality.issue.close"].includes(operation) && cap.receipt_subject_type !== "quality_issue")) return null;
  }
  if (!Array.isArray(x.late_links) || !x.late_links.every(v => materialRow(v) &&
      hasKeys(v, ["ref", "issue_id", "meaning", "formal", "run", "current_evaluation", "source_status", "missing"]) && v.issue_id === issue.issue_id &&
      ["planned", "performed"].includes(String(v.meaning)) && validRef(v.formal) && (v.run === null || validRef(v.run)))) return null;
  if (!Array.isArray(x.candidates) || !x.candidates.every(v => materialRow(v) &&
      hasKeys(v, ["ref", "anchor", "late_link", "applicable", "independently_verified", "observation_complete", "result", "current_evaluation", "source_status", "missing"]) && validMaterial(v.anchor) && validMaterial(v.late_link) &&
      v.applicable === null && v.independently_verified === null && v.observation_complete === null && v.result === "indeterminate")) return null;
  if (!Array.isArray(x.rule_publications) || !x.rule_publications.every(v => materialRow(v) &&
      hasKeys(v, ["ref", "publication", "issuer_key", "issuer_version", "issuer_epoch", "nature", "source_status", "current_evaluation", "valid_from", "valid_until", "missing"]) && v.publication === "host_only" &&
      text(v.issuer_key) && text(v.issuer_version) && positive(v.issuer_epoch) && ["real", "synthetic"].includes(String(v.nature)) &&
      eventTime(v.valid_from) !== null && eventTime(v.valid_until) !== null && Date.parse(String(v.valid_until)) > Date.parse(String(v.valid_from)))) return null;
  if (!Array.isArray(x.observations) || !x.observations.every(v => materialRow(v) &&
      hasKeys(v, ["ref", "rule", "observed_from", "observed_until", "occurred_at", "original_timezone", "current_evaluation", "source_status", "missing"]) && validMaterial(v.rule) &&
      eventTime(v.observed_from) !== null && eventTime(v.observed_until) !== null && eventTime(v.occurred_at) !== null && eventTimezone(v.original_timezone) !== null)) return null;
  if (!Array.isArray(x.reviews) || !x.reviews.every(v => materialRow(v) &&
      hasKeys(v, ["ref", "candidate", "rule", "observations", "reviewer_id", "conclusion", "occurred_at", "original_timezone", "current_evaluation", "source_status", "missing"]) && validMaterial(v.candidate) && validMaterial(v.rule) &&
      Array.isArray(v.observations) && v.observations.every(validMaterial) && uuid(v.reviewer_id) &&
      ["applicable", "not_applicable", "unknown"].includes(String(v.conclusion)) && eventTime(v.occurred_at) !== null && eventTimezone(v.original_timezone) !== null)) return null;
  if (x.effectiveness !== null && (!record(x.effectiveness) || !hasKeys(x.effectiveness, ["issue_ref", "actor_id", "outcome"]) ||
      !validRef(x.effectiveness.issue_ref) || !uuid(x.effectiveness.actor_id) || !["effective", "ineffective"].includes(String(x.effectiveness.outcome)))) return null;
  return snapshot(x as unknown as Model);
}
