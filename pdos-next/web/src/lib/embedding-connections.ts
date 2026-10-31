/** Public managed connection selection; credentials are transient request input only. */
import type { ModelConnection } from "@/components/model_configuration/contracts";
import type { AddConnectionRequest } from "@/components/model_configuration/connection-editor";
import type { EmbeddingMetadata } from "@/lib/embedding-settings";

export type EmbeddingConnection = { id: string; name: string; base_url: string; model: string; model_version: string; provider: string; pricing_configured: boolean };
export type EmbeddingConnectionForm = { name: string; base: string; model: string; version: string; key: string; priced: boolean; source: string; inputRate: string; requestFee: string; byteBound: string; framing: string; verified: boolean };
const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
function validEndpoint(value: string) {
  try { const url = new URL(value); return value.length <= 500 && !!url.hostname && !url.username && !url.password && !url.search && !url.hash && (url.protocol === "https:" || url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)); } catch { return false; }
}
export function embeddingConnectionFrom(value: ModelConnection): EmbeddingConnection | null {
  const metadata = value?.metadata, name = /^[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}$/;
  if (!uuid(value?.id) || typeof value.name !== "string" || !value.name || typeof value.provider !== "string" || typeof value.pricing_configured !== "boolean" || metadata?.protocol !== "openai-compatible" || !validEndpoint(metadata.base_url) || typeof metadata.model !== "string" || !name.test(metadata.model) || typeof metadata.model_version !== "string" || !name.test(metadata.model_version) || metadata.connection_id !== value.id) return null;
  return { id: value.id, name: value.name, base_url: metadata.base_url, model: metadata.model, model_version: metadata.model_version, provider: value.provider, pricing_configured: value.pricing_configured };
}
export function embeddingConnectionMetadata(connection: EmbeddingConnection): Pick<EmbeddingMetadata, "connection_id" | "base_url" | "model" | "model_version"> {
  return { connection_id: connection.id, base_url: connection.base_url.replace(/\/+$/, ""), model: connection.model, model_version: connection.model_version };
}
export function newEmbeddingConnectionRequest(form: EmbeddingConnectionForm, checkedAt = new Date()): AddConnectionRequest {
  const base = form.base.trim().replace(/\/+$/, ""), model = form.model.trim(), version = form.version.trim(), key = form.key.trim(), name = form.name.trim() || model;
  const modelName = /^[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}$/;
  if (!validEndpoint(base) || !modelName.test(model) || !modelName.test(version) || name.length > 120) throw new Error("请填写有效的独立 Embedding 端点、模型、版本和显示名称。");
  if (!key || key.length > 8192 || /[^\x21-\x7e]/.test(key)) throw new Error("请填写有效的 API Key，密钥仅发送至服务器安全存储。");
  let pricing: AddConnectionRequest["pricing"] = null;
  if (form.priced) {
    const decimal = /^(?:0|[1-9]\d*)(?:\.\d+)?$/;
    if (!form.verified || !form.source.trim() || form.source.length > 2000 || ![form.inputRate, form.requestFee, form.byteBound].every(value => decimal.test(value) && Number.isFinite(Number(value))) || Number(form.byteBound) < 1 || !/^\d+$/.test(form.framing) || !Number.isSafeInteger(Number(form.framing)) || Number(form.framing) > 2147483647 || !Number.isFinite(checkedAt.getTime())) throw new Error("请核对价格依据、全部费用及文本计费上界，再确认计量资料。");
    const source = form.source.trim();
    pricing = { input_per_million: form.inputRate, output_per_million: "0", cache_read_per_million: "0", cache_creation_per_million: "0", request_fee: form.requestFee, text_tokens_per_utf8_byte: form.byteBound, text_framing_tokens: Number(form.framing), source, text_billing_source: source, verified_at: checkedAt.toISOString(), valid_until: new Date(checkedAt.getTime() + 30 * 86400000).toISOString(), currency: "USD", output_cap_covers_all_billing: true, covers_all_fees: true };
  }
  return { request_id: crypto.randomUUID(), name, api_key: key, pricing, metadata: { protocol: "openai-compatible", base_url: base, model, model_version: version, max_output_tokens: 2048, openai_output_parameter: "max_completion_tokens", timeout_seconds: 30, response_bytes: 1048576 } };
}
