import type { PaiInputSource, PaiSourcesScope } from "./pai-sources";

export type PaiUploadScope = PaiSourcesScope;
export type PaiUploadApi = <T>(path: string, body?: unknown) => Promise<T>;
export const MAX_UPLOAD_BYTES = 8_388_608;
export const MAX_UPLOAD_BASE64 = 11_184_812;
export const MAX_UPLOAD_JSON_BYTES = MAX_UPLOAD_BASE64 + 16_384;
export type PaiUploadTargetIdentity = { kind: "category" | "product"; id: string; revision: number };
type Scope = { category_id: string; product_id: string | null; proposal_id: string | null };
export type PaiUploadTarget = {
  version: "agent-upload-target/v1"; principal_id: string; scope: Scope; as_of: string; target: PaiUploadTargetIdentity;
  authorization: { can_write: boolean; code: null | "FORBIDDEN_SCOPE" };
  constraints: { max_bytes: 8388608; extensions: string[]; default_visibility: "private" };
};
export type PaiUploadReceipt = {
  version: "agent-upload-receipt/v1"; principal_id: string; scope: Scope; as_of: string; request_key: string; request_digest: string;
  state: "committed" | "reserved" | "abandoned" | "not_observed";
  receipt: null | { id: string; operation: "evidence.original.upload"; subject_type: "uploaded_original"; subject_id: string; subject_revision: number; writer_id: string; requester_id: string; created_at: string };
  attempt: null | { id: string; revision: number; status: "reserved" | "committed" | "abandoned" };
  original: null | { id: string; revision: number; title: string; filename: string; parse_status: string; parse_code: string | null; scan_status: string; security: { state: string; reasons: string[]; epoch: number; source_state: "active" | "withdrawn" } };
  source: PaiInputSource | null;
};
export type PaiUploadVisibility = "private" | "category" | "audience";
type Metadata = { filename: string; title: string; source_label: string; visibility: PaiUploadVisibility; expected_revision: number };
export type PaiUploadPointer = {
  version: "pai-upload-pointer/v1"; principal_id: string; scope: Scope; target: PaiUploadTargetIdentity;
  request_key: string; request_digest: string; file: { byte_count: number; content_hash: string }; metadata: Metadata;
};
export type PaiUploadBody = Metadata & { content_base64: string; idempotency_key: string };
export type PaiUploadIntent = { pointer: PaiUploadPointer; body: PaiUploadBody };
export type PaiUploadFile = { name: string; size: number; arrayBuffer(): Promise<ArrayBuffer> };
export type PaiUploadMetadata = { title?: string; sourceLabel: string; visibility?: PaiUploadVisibility };

const object = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const keys = (v: Record<string, unknown>, expected: string[]) => Object.keys(v).length === expected.length && expected.every(k => Object.hasOwn(v, k));
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const hash = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{64}$/.test(v);
const integer = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v > 0;
const text = (v: unknown): v is string => typeof v === "string" && v.length > 0;
const nullableText = (v: unknown) => v === null || typeof v === "string";
const nullableUuid = (v: unknown) => v === null || uuid(v);
const sameId = (a: unknown, b: unknown) => typeof a === "string" && typeof b === "string" ? a.toLowerCase() === b.toLowerCase() : a === b;
const iso = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
function invalid(): never { throw new Error("上传身份、原请求或服务器回执无法核对，请保留原请求并重新读取。"); }

/** Python str.strip whitespace, deliberately excluding JavaScript's extra FEFF. */
export function pythonWhitespaceStrip(value: string): string {
  return value.replace(/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g, "");
}
function cleanText(value: unknown, max: number): value is string {
  return text(value) && pythonWhitespaceStrip(value) === value && [...value].length <= max;
}
function scopeShape(value: unknown): value is Scope {
  return object(value) && keys(value, ["category_id", "product_id", "proposal_id"]) && uuid(value.category_id) && nullableUuid(value.product_id) && nullableUuid(value.proposal_id);
}
function inputScope(scope: PaiUploadScope): Scope {
  if (!object(scope) || !uuid(scope.principalId) || !uuid(scope.categoryId) || !nullableUuid(scope.productId) || !nullableUuid(scope.proposalId)) invalid();
  return { category_id: scope.categoryId, product_id: scope.productId, proposal_id: scope.proposalId };
}
function sameScope(value: unknown, expected: Scope): value is Scope {
  return scopeShape(value) && sameId(value.category_id, expected.category_id) && sameId(value.product_id, expected.product_id) && sameId(value.proposal_id, expected.proposal_id);
}
function targetIdentity(value: unknown, scope: Scope): value is PaiUploadTargetIdentity {
  return object(value) && keys(value, ["kind", "id", "revision"]) && integer(value.revision)
    && (scope.product_id === null ? value.kind === "category" && sameId(value.id, scope.category_id) : value.kind === "product" && sameId(value.id, scope.product_id));
}
function target(value: unknown): value is PaiUploadTarget {
  return object(value) && keys(value, ["version", "principal_id", "scope", "as_of", "target", "authorization", "constraints"])
    && value.version === "agent-upload-target/v1" && uuid(value.principal_id) && scopeShape(value.scope) && iso(value.as_of) && targetIdentity(value.target, value.scope)
    && object(value.authorization) && keys(value.authorization, ["can_write", "code"]) && typeof value.authorization.can_write === "boolean"
    && value.authorization.code === (value.authorization.can_write ? null : "FORBIDDEN_SCOPE")
    && object(value.constraints) && keys(value.constraints, ["max_bytes", "extensions", "default_visibility"])
    && value.constraints.max_bytes === MAX_UPLOAD_BYTES && value.constraints.default_visibility === "private"
    && Array.isArray(value.constraints.extensions) && value.constraints.extensions.length === 4
    && new Set(value.constraints.extensions).size === 4 && [".txt", ".md", ".pdf", ".xlsx"].every(ext => (value.constraints as { extensions: unknown[] }).extensions.includes(ext));
}
function metadata(value: unknown): value is Metadata {
  return object(value) && keys(value, ["filename", "title", "source_label", "visibility", "expected_revision"])
    && cleanText(value.filename, 200) && !/[\x00-\x1f/\\]/.test(value.filename) && new TextEncoder().encode(value.filename).length <= 600
    && /\.(txt|md|pdf|xlsx)$/i.test(value.filename) && cleanText(value.title, 200) && cleanText(value.source_label, 200)
    && ["private", "category", "audience"].includes(String(value.visibility)) && integer(value.expected_revision);
}
const sha256 = async (bytes: Uint8Array): Promise<string> => [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes as Uint8Array<ArrayBuffer>))].map(v => v.toString(16).padStart(2, "0")).join("");
async function requestDigest(meta: Metadata, content_hash: string): Promise<string> {
  const fields = { content_hash, expected_revision: meta.expected_revision, filename: meta.filename, source_label: meta.source_label, title: meta.title, visibility: meta.visibility };
  return sha256(new TextEncoder().encode(JSON.stringify(fields)));
}
function pointerShape(value: unknown): value is PaiUploadPointer {
  return object(value) && keys(value, ["version", "principal_id", "scope", "target", "request_key", "request_digest", "file", "metadata"])
    && value.version === "pai-upload-pointer/v1" && uuid(value.principal_id) && scopeShape(value.scope) && targetIdentity(value.target, value.scope)
    && uuid(value.request_key) && hash(value.request_digest) && object(value.file) && keys(value.file, ["byte_count", "content_hash"])
    && integer(value.file.byte_count) && value.file.byte_count <= MAX_UPLOAD_BYTES && hash(value.file.content_hash)
    && metadata(value.metadata) && value.metadata.expected_revision === value.target.revision;
}
export async function restoreUploadPointer(value: unknown, scope: PaiUploadScope): Promise<PaiUploadPointer | null> {
  const expected = inputScope(scope);
  if (!pointerShape(value) || !sameId(value.principal_id, scope.principalId) || !sameScope(value.scope, expected)
    || await requestDigest(value.metadata, value.file.content_hash) !== value.request_digest) return null;
  return JSON.parse(JSON.stringify(value)) as PaiUploadPointer;
}
function scopeFor(value: { principal_id: string; scope: Scope }): PaiUploadScope {
  return { principalId: value.principal_id, categoryId: value.scope.category_id, productId: value.scope.product_id, proposalId: value.scope.proposal_id };
}
function query(scope: Scope): URLSearchParams {
  const result = new URLSearchParams();
  if (scope.product_id) result.set("product_id", scope.product_id);
  if (scope.proposal_id) result.set("proposal_id", scope.proposal_id);
  return result;
}
function withQuery(path: string, params: URLSearchParams): string { return `${path}${params.size ? `?${params}` : ""}`; }
export async function readUploadTarget(api: PaiUploadApi, scope: PaiUploadScope): Promise<PaiUploadTarget> {
  const expected = inputScope(scope), value = await api<unknown>(withQuery(`v1/categories/${scope.categoryId}/agent-upload-target`, query(expected)));
  if (!target(value) || !sameId(value.principal_id, scope.principalId) || !sameScope(value.scope, expected)) invalid();
  return value;
}

export async function createUploadIntent(file: PaiUploadFile, declared: PaiUploadMetadata, currentTarget: PaiUploadTarget, originalPointer?: PaiUploadPointer): Promise<PaiUploadIntent> {
  if (!target(currentTarget) || !currentTarget.authorization.can_write || !object(file) || !text(file.name) || !integer(file.size) || file.size > MAX_UPLOAD_BYTES || typeof file.arrayBuffer !== "function") invalid();
  const prior = originalPointer === undefined ? null : await restoreUploadPointer(originalPointer, scopeFor(currentTarget));
  if (originalPointer !== undefined && !prior) invalid();
  const filename = pythonWhitespaceStrip(file.name);
  let meta: Metadata;
  if (prior) {
    if (filename !== prior.metadata.filename || file.size !== prior.file.byte_count || !sameId(prior.target.id, currentTarget.target.id) || prior.target.kind !== currentTarget.target.kind) invalid();
    meta = { ...prior.metadata };
  } else {
    if (!object(declared) || Object.keys(declared).some(key => !["title", "sourceLabel", "visibility"].includes(key)) || typeof declared.sourceLabel !== "string" || !(declared.title === undefined || typeof declared.title === "string")) invalid();
    meta = { filename, title: pythonWhitespaceStrip(declared.title ?? filename), source_label: pythonWhitespaceStrip(declared.sourceLabel), visibility: declared.visibility ?? "private", expected_revision: currentTarget.target.revision };
  }
  if (!metadata(meta)) invalid();
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes.length !== file.size) invalid();
  const content_hash = await sha256(bytes), request_digest = await requestDigest(meta, content_hash);
  if (prior && (content_hash !== prior.file.content_hash || request_digest !== prior.request_digest)) invalid();
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  const pointer: PaiUploadPointer = prior ?? { version: "pai-upload-pointer/v1", principal_id: currentTarget.principal_id, scope: { ...currentTarget.scope }, target: { ...currentTarget.target }, request_key: crypto.randomUUID(), request_digest, file: { byte_count: file.size, content_hash }, metadata: meta };
  return { pointer, body: { ...pointer.metadata, content_base64: btoa(binary), idempotency_key: pointer.request_key } };
}

function sourceHead(value: unknown): value is PaiInputSource {
  if (!object(value) || !keys(value, ["artifact_id", "artifact_revision", "title", "product_id", "status", "original", "availability"])
    || !uuid(value.artifact_id) || !integer(value.artifact_revision) || !text(value.title) || !nullableUuid(value.product_id) || !["active", "withdrawn"].includes(String(value.status))
    || !object(value.availability) || !keys(value.availability, ["available", "code"]) || typeof value.availability.available !== "boolean") return false;
  if (value.availability.available ? value.status !== "active" || value.availability.code !== null : !text(value.availability.code)) return false;
  const original = value.original;
  return original === null || object(original) && keys(original, ["id", "revision", "filename", "parse_status", "parse_code", "scan_status"])
    && uuid(original.id) && integer(original.revision) && text(original.filename) && text(original.parse_status) && nullableText(original.parse_code) && text(original.scan_status);
}
function receiptShape(value: unknown, scope: PaiUploadScope, pointer: PaiUploadPointer): value is PaiUploadReceipt {
  if (!object(value) || !keys(value, ["version", "principal_id", "scope", "as_of", "request_key", "request_digest", "state", "receipt", "attempt", "original", "source"])
    || value.version !== "agent-upload-receipt/v1" || !sameId(value.principal_id, scope.principalId) || !sameScope(value.scope, pointer.scope)
    || !iso(value.as_of) || !sameId(value.request_key, pointer.request_key) || value.request_digest !== pointer.request_digest) return false;
  const { receipt, attempt, original, source } = value;
  if (attempt !== null && (!object(attempt) || !keys(attempt, ["id", "revision", "status"]) || !uuid(attempt.id) || !integer(attempt.revision) || !["reserved", "committed", "abandoned"].includes(String(attempt.status)))) return false;
  if (value.state === "not_observed") return receipt === null && attempt === null && original === null && source === null;
  if (value.state === "reserved" || value.state === "abandoned") return receipt === null && object(attempt) && attempt.status === value.state && original === null && source === null;
  if (value.state !== "committed" || !object(receipt) || !keys(receipt, ["id", "operation", "subject_type", "subject_id", "subject_revision", "writer_id", "requester_id", "created_at"])
    || !uuid(receipt.id) || receipt.operation !== "evidence.original.upload" || receipt.subject_type !== "uploaded_original" || !uuid(receipt.subject_id) || !integer(receipt.subject_revision)
    || !sameId(receipt.writer_id, scope.principalId) || !sameId(receipt.requester_id, scope.principalId) || !iso(receipt.created_at)
    || attempt !== null && (!object(attempt) || attempt.status !== "committed" || !sameId(attempt.id, receipt.subject_id))) return false;
  if (original === null) return source === null;
  if (!object(original) || !keys(original, ["id", "revision", "title", "filename", "parse_status", "parse_code", "scan_status", "security"])
    || !sameId(original.id, receipt.subject_id) || !integer(original.revision) || !text(original.title) || !text(original.filename) || !text(original.parse_status) || !nullableText(original.parse_code) || !text(original.scan_status)
    || !object(original.security) || !keys(original.security, ["state", "reasons", "epoch", "source_state"]) || !text(original.security.state) || !integer(original.security.epoch)
    || !Array.isArray(original.security.reasons) || !original.security.reasons.every(reason => typeof reason === "string") || !["active", "withdrawn"].includes(String(original.security.source_state))) return false;
  return source === null || sourceHead(source) && sameId(source.product_id, pointer.scope.product_id) && source.original !== null
    && sameId(source.original.id, original.id) && source.original.revision === original.revision;
}
export async function readUploadReceipt(api: PaiUploadApi, scope: PaiUploadScope, original: PaiUploadPointer): Promise<PaiUploadReceipt> {
  const pointer = await restoreUploadPointer(original, scope);
  if (!pointer) invalid();
  const params = query(pointer.scope); params.set("request_digest", pointer.request_digest);
  const value = await api<unknown>(withQuery(`v1/categories/${scope.categoryId}/agent-upload-receipts/${pointer.request_key}`, params));
  if (!receiptShape(value, scope, pointer)) invalid();
  return value;
}

/** Status survives HTML/empty errors; this transport never retries an upload. */
export const paiUploadApi: PaiUploadApi = async <T>(resource: string, body?: unknown): Promise<T> => {
  const response = await fetch(`/api/${resource}`, { method: body === undefined ? "GET" : "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
  const raw = await response.text(); let value: unknown;
  try { value = raw ? JSON.parse(raw) : null; } catch { value = null; }
  if (!response.ok) throw Object.assign(new Error(object(value) && typeof value.message === "string" && !/storage[_ -]?key|traceback|stack trace/i.test(value.message) ? value.message : response.status === 413 ? "上传请求超过接收大小限制。" : response.status === 401 || response.status === 403 ? "当前身份或上传范围不可用。" : "尚未取得上传回执，请保留原请求核对。"), { status: response.status, code: object(value) && typeof value.code === "string" ? value.code : response.status === 413 ? "FILE_TOO_LARGE" : "UPLOAD_RESPONSE_UNAVAILABLE" });
  return value as T;
};

/** Only the nonce/digest read-back is authoritative, including after a lost POST response. */
export async function uploadOriginal(api: PaiUploadApi, scope: PaiUploadScope, intent: PaiUploadIntent): Promise<{ reading: PaiUploadReceipt; postError: Error | null }> {
  const pointer = await restoreUploadPointer(intent?.pointer, scope);
  if (!pointer || !object(intent.body) || !keys(intent.body, ["filename", "title", "source_label", "visibility", "expected_revision", "content_base64", "idempotency_key"])
    || !Object.entries(pointer.metadata).every(([key, value]) => intent.body[key as keyof PaiUploadBody] === value)
    || intent.body.idempotency_key !== pointer.request_key || typeof intent.body.content_base64 !== "string" || !validUploadBody(intent.body)) invalid();
  const bytes = Uint8Array.from(atob(intent.body.content_base64), char => char.charCodeAt(0));
  if (bytes.length !== pointer.file.byte_count || await sha256(bytes) !== pointer.file.content_hash) invalid();
  const destination = `v1/categories/${scope.categoryId}/${scope.productId ? `products/${scope.productId}/` : ""}originals`;
  let postError: Error | null = null;
  const errorFor = (failure: unknown) => Object.assign(new Error(object(failure) && typeof failure.message === "string" ? failure.message : "原上传回执尚待核对。"), {
    ...(object(failure) && typeof failure.status === "number" ? { status: failure.status } : {}),
    ...(object(failure) && typeof failure.code === "string" ? { code: failure.code } : {}),
  });
  try { await api<unknown>(destination, intent.body); }
  catch (failure) { postError = errorFor(failure); }
  let reading: PaiUploadReceipt;
  try { reading = await readUploadReceipt(api, scope, pointer); }
  catch (failure) { throw Object.assign(errorFor(failure), { postResponseReceived: postError === null, postError }); }
  return { reading, postError };
}

/** Shared transport validation; server domain guards still own write authority. */
export function validUploadBody(value: unknown): boolean {
  if (!object(value) || Object.keys(value).some(key => !["filename", "title", "source_label", "visibility", "expected_revision", "content_base64", "idempotency_key"].includes(key))) return false;
  const normalize = (item: unknown) => typeof item === "string" ? pythonWhitespaceStrip(item) : item;
  const meta = { filename: normalize(value.filename), title: normalize(value.title), source_label: normalize(value.source_label), visibility: normalize(value.visibility ?? "private"), expected_revision: value.expected_revision };
  const base64 = normalize(value.content_base64), nonce = normalize(value.idempotency_key);
  if (!metadata(meta) || !text(nonce) || nonce.length < 8 || [...nonce].length > 160 || typeof base64 !== "string" || base64.length < 4 || base64.length > MAX_UPLOAD_BASE64 || base64.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(base64)) return false;
  const decoded = base64.length / 4 * 3 - (base64.endsWith("==") ? 2 : base64.endsWith("=") ? 1 : 0);
  return decoded > 0 && decoded <= MAX_UPLOAD_BYTES;
}
