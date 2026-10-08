import type { BasisBindingView, PoolChoice, SupplyConfirmation, SupplyDraft, SupplyEntryPreview, SupplyEntryReceipt } from "./types";

export const recordLabels = { commitment: "供方承诺", in_transit: "在途", receipt: "实际到货", inventory: "库存", restriction: "质量/可用限制" };
export const qualityLabels = { released: "已释放", frozen: "冻结/待检", unknown: "质量未知" };
export const availabilityLabels = { available: "可用", unavailable: "不可用", unknown: "可用性未知" };
export const freshnessLabels = { current: "当前依据", requires_recalculation: "需要重新核算", historical: "历史依据" };
export function quantity(value: string | null | undefined, unit?: string | null) { return value == null ? "未知" : `${value}${unit ? ` ${unit}` : ""}`; }
export function readiness(value: boolean | null, complete: string) { return value === true ? complete : value === false ? "已知缺项" : "未确定"; }
export function poolKey(pool: { source_system: string; pool_id: string; material_id: string }) { return `${pool.source_system} · ${pool.pool_id} · ${pool.material_id}`; }
export function failureMessage(failure: unknown) { return failure instanceof Error ? failure.message : "办理失败，请核对当前来源后重试。"; }
export function sourceChoiceKey(source: { source_id: string; version: string }) { return JSON.stringify([source.source_id, source.version]); }
export function selectablePools(pools: PoolChoice[], materialId: string) {
  const distinct = [...new Map(pools.filter(pool => pool.key.material_id === materialId).map(pool => [JSON.stringify(pool.key), pool])).values()];
  return distinct.map(pool => ({ ...pool, ambiguous: distinct.some(other => other.key.pool_id === pool.key.pool_id && other.key.source_system !== pool.key.source_system) }));
}

/** Client checks prevent unusable previews. Server rechecks authority and freshness at commit. */
export function checkPreview(preview: SupplyEntryPreview, draft: SupplyDraft, binding: BasisBindingView, now = Date.now()): void {
  if (!preview.review_id || !preview.confirmation_token || !/^[a-f0-9]{64}$/.test(preview.binding_sha256)) throw new Error("服务器预览凭据不完整，尚未提交。");
  if (!Number.isFinite(Date.parse(preview.expires_at)) || Date.parse(preview.expires_at) <= now) throw new Error("预览已经过期，请重新取得当前预览。");
  if (preview.basis_binding.basis_sha256 !== binding.basis_sha256 || preview.basis_binding.demand_sha256 !== binding.demand_sha256) throw new Error("Build 或需求版本已经变化，请刷新固定依据。");
  if (preview.basis_binding.basis.build.ref.sha256 !== binding.basis.build.ref.sha256 || preview.basis_binding.basis.bom.ref.sha256 !== binding.basis.bom.ref.sha256 || preview.basis_binding.basis.bom.engineering_configuration.sha256 !== binding.basis.bom.engineering_configuration.sha256 || preview.basis_binding.manufacturing_configuration.sha256 !== binding.manufacturing_configuration.sha256) throw new Error("固定配置或来源内容已经变化，请刷新固定依据。");
  if (preview.source.source_id !== draft.source_id || preview.source.version !== draft.source_revision || preview.source.state !== "current") throw new Error("来源版本已变化或不可用，请重新选择当前来源。");
  if (preview.source.valid_until !== null && (!Number.isFinite(Date.parse(preview.source.valid_until)) || Date.parse(preview.source.valid_until) <= now)) throw new Error("来源已经过期，请重新取得当前预览。");
  if (preview.record.source_id !== preview.source.source_id || preview.record.source_revision !== preview.source.version || !preview.record.record_id || !preview.record.material_id || !preview.changes.length) throw new Error("预览缺少实质字段或固定来源，尚未提交。");
}
export function confirmationFor(preview: SupplyEntryPreview, now = Date.now()): SupplyConfirmation {
  if (!preview.allowed_to_confirm) throw new Error("当前预览需要其他具名办理，不能在此确认。");
  if (!Number.isFinite(Date.parse(preview.expires_at)) || Date.parse(preview.expires_at) <= now) throw new Error("预览已经过期，请重新取得当前预览。");
  return { review_id: preview.review_id, confirmation_token: preview.confirmation_token, binding_sha256: preview.binding_sha256 };
}
export function checkReceipt(receipt: SupplyEntryReceipt, preview: SupplyEntryPreview): void {
  if (receipt.status !== "persisted" || receipt.review_id !== preview.review_id || !receipt.receipt_id || !receipt.snapshot_id || !receipt.snapshot_revision) throw new Error("保存结果尚未确认，请使用本次确认凭据回查，避免重复录入。");
}
