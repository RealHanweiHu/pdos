/** Account metadata/requests only. Server resolves identity, READ and outbound policy. */
export type DingApi = <T>(path: string, body?: unknown) => Promise<T>;
type Row = Record<string, unknown>;
const record = (v: unknown): v is Row => !!v && typeof v === "object" && !Array.isArray(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(v);
const text = (v: unknown, max = 200): v is string => typeof v === "string" && v.length > 0 && v.length <= max;
const natural = (v: unknown, min = 1): v is number => Number.isSafeInteger(v) && Number(v) >= min;
const fields = (v: Row, allowed: string[]) => Object.keys(v).every(k => allowed.includes(k));
export type DingApplication = { application_id: string; revision: number; active: boolean; corp_id?: string; client_id?: string; robot_code?: string; secret_arn?: string; secret_version?: string };
export type DingBinding = { binding_id: string; application_id: string; owner_id: string; active: boolean; epoch: number; verified_at: string };
export type DingSettings = { principal_id: string; can_manage: boolean; configured: boolean; group_citations_available: boolean; application: DingApplication | null; bindings: DingBinding[]; has_more_bindings: boolean };
export function parseDingSettings(v: unknown, expectedPrincipal: string): DingSettings {
  if (!record(v) || v.principal_id !== expectedPrincipal || typeof v.can_manage !== "boolean" || typeof v.configured !== "boolean" || typeof v.group_citations_available !== "boolean" || typeof v.has_more_bindings !== "boolean" || !Array.isArray(v.bindings)) throw new Error("尚未读取到当前本人钉钉设置。");
  if (v.application !== null && (!record(v.application) || !uuid(v.application.application_id) || !natural(v.application.revision) || typeof v.application.active !== "boolean" || v.can_manage && !["corp_id", "client_id", "robot_code", "secret_arn", "secret_version"].every(k => text((v.application as Row)[k], 2000)))) throw new Error("应用登记尚未核实。");
  if (!v.bindings.every(b => record(b) && uuid(b.binding_id) && uuid(b.application_id) && uuid(b.owner_id) && natural(b.epoch) && typeof b.active === "boolean" && text(b.verified_at) && (v.can_manage || b.owner_id === expectedPrincipal))) throw new Error("账号绑定不属于当前读取范围。");
  return v as DingSettings;
}
export type BindStart = { principalId: string; applicationId: string; state: string; expiresAt: string };
export const bindingStorageKey = (principalId: string) => `pdos-next:dingtalk-binding:${principalId}`;
export function parseBindStart(v: unknown, principalId: string, at = Date.now()): BindStart | null {
  if (!record(v) || !fields(v, ["principalId", "applicationId", "state", "expiresAt"]) || v.principalId !== principalId || !uuid(v.applicationId) || !text(v.state, 200) || !text(v.expiresAt) || !Number.isFinite(Date.parse(v.expiresAt)) || Date.parse(v.expiresAt) <= at) return null;
  return v as BindStart;
}
export function prepareBindStart(v: unknown, principalId: string, applicationId: string, origin: string, at = Date.now()) {
  if (!record(v) || !text(v.authorization_url, 4000) || !text(v.expires_at)) throw new Error("一次性绑定请求尚未核实。");
  const url = new URL(v.authorization_url), callback = new URL(url.searchParams.get("redirect_uri") ?? "");
  if (url.origin !== "https://login.dingtalk.com" || url.pathname !== "/oauth2/auth" || callback.origin !== origin || callback.pathname !== "/" || callback.searchParams.get("area") !== "settings" || callback.searchParams.get("dingtalk_callback") !== "1") throw new Error("授权跳转未指向当前 PDOS 本人设置。");
  const pending = parseBindStart({ principalId, applicationId, state: url.searchParams.get("state"), expiresAt: v.expires_at }, principalId, at);
  if (!pending) throw new Error("一次性绑定状态已过期。");
  return { pending, url: url.href };
}
export function bindingCallback(search: string, pending: BindStart | null, at = Date.now()) {
  const q = new URLSearchParams(search);
  if (q.get("dingtalk_callback") !== "1") return null;
  if (!pending || !parseBindStart(pending, pending.principalId, at) || q.getAll("state").length !== 1 || q.get("state") !== pending.state || q.getAll("authCode").length !== 1 || !text(q.get("authCode"), 4096) || q.has("error")) throw new Error("授权返回与本人一次性绑定请求不一致，请重新发起绑定。");
  return { application_id: pending.applicationId, state: pending.state, auth_code: q.get("authCode")! };
}
export function removeCallback(search: string) { const q = new URLSearchParams(search); for (const k of ["authCode", "state", "error", "dingtalk_callback"]) q.delete(k); return `/?${q}`; }
export const dingPaths = (p: string) => p === "v1/dingtalk/application" || /^v1\/personal\/dingtalk\/(?:settings|bindings(?:\/(?:begin|finish|revoke))?|share\/(?:preview|confirm)|deliveries(?:\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/reconcile)?)$/i.test(p);
export function dingMethod(p: string) { return /\/(?:settings|bindings|deliveries)$/.test(p) ? "GET" : "POST"; }
export function validDingBody(path: string, v: unknown) {
  if (!dingPaths(path) || dingMethod(path) !== "POST" || !record(v)) return false;
  if (path === "v1/dingtalk/application") return fields(v, ["expected_revision", "corp_id", "client_id", "robot_code", "secret_arn", "secret_version", "active"]) && natural(v.expected_revision, 0) && ["corp_id", "client_id", "robot_code", "secret_version"].every(k => text(v[k], 160)) && typeof v.secret_arn === "string" && /^acs:kms:[a-z0-9-]+:[0-9]+:secret\/[^\s]+$/.test(v.secret_arn) && typeof v.active === "boolean";
  if (path.endsWith("/begin")) return fields(v, ["application_id"]) && uuid(v.application_id);
  if (path.endsWith("/finish")) return fields(v, ["application_id", "state", "auth_code"]) && uuid(v.application_id) && text(v.state, 200) && text(v.auth_code, 4096);
  if (path.endsWith("/revoke")) return fields(v, ["binding_id", "expected_epoch", "reason", "request_key"]) && uuid(v.binding_id) && natural(v.expected_epoch) && text(v.reason, 500) && uuid(v.request_key);
  if (path.endsWith("/reconcile")) return Object.keys(v).length === 0;
  const preview = path.endsWith("/preview");
  return fields(v, preview ? ["run_id", "include_citations"] : ["run_id", "include_citations", "preview_digest", "request_key"]) && uuid(v.run_id) && typeof v.include_citations === "boolean" && (preview || typeof v.preview_digest === "string" && /^[a-f0-9]{64}$/.test(v.preview_digest) && uuid(v.request_key));
}
export type DingPreview = { run_id: string; payload: { target_kind: "group"; target_id: string; text: string; url: string; citations?: { title?: string; quote?: string }[] }; preview_digest: string; withheld_reason: string | null; citations_included: boolean };
export function parseDingPreview(v: unknown, runId: string, origin: string): DingPreview {
  if (!record(v) || v.run_id !== runId || !record(v.payload) || v.payload.target_kind !== "group" || !text(v.payload.target_id) || typeof v.payload.text !== "string" || !text(v.payload.url, 2000) || typeof v.preview_digest !== "string" || !/^[a-f0-9]{64}$/.test(v.preview_digest) || typeof v.citations_included !== "boolean") throw new Error("尚未取得匹配的原群分享预览。");
  const url = new URL(v.payload.url);
  if (url.origin !== origin || url.pathname !== `/dingtalk/runs/${runId}` || url.search || url.hash || url.protocol !== "https:") throw new Error("继续链接尚未核实。");
  if (v.payload.citations !== undefined && (!Array.isArray(v.payload.citations) || !v.payload.citations.every(c => record(c) && (c.title === undefined || typeof c.title === "string") && (c.quote === undefined || typeof c.quote === "string")))) throw new Error("引文预览尚未核实。");
  return v as DingPreview;
}
