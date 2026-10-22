import { matchesProposalDocument, type ProposalViewDocument, type ProposalViewSource } from "@/components/preproject/proposal-view-contracts";

export type ProposalVoiceEntry = {
  knowledge_id: string; lineage_id: string; version: number;
  label: string; source_platform: string; origin: string; status: string;
  current_version: number | null; sample_size: number | null;
  source_refs: ProposalViewSource[]; representative_refs: ProposalViewSource[];
  related_items: { item_id: string; version: number; kind: string; label: string }[];
  used_in_context: boolean; source_changes: Readonly<Record<string, unknown>>[];
};
export type ProposalVoiceUnavailable = { reference: { type: "knowledge"; id?: string | number; version?: string | number }; reasons: string[] };
export type ProposalVoicesResponse = {
  version: "proposal-voices/v1"; category_id: string; document: ProposalViewDocument; as_of: string;
  entries: ProposalVoiceEntry[]; unavailable: ProposalVoiceUnavailable[];
  counts: { entries: number; unavailable_entries: number };
};
export type ProposalVoicesReader = (path: string, signal: AbortSignal) => Promise<unknown>;

export function proposalVoicesPath(categoryId: string, proposalId: string) {
  return `/api/v1/categories/${encodeURIComponent(categoryId)}/proposals/${encodeURIComponent(proposalId)}/voices`;
}

export const readProposalVoices: ProposalVoicesReader = async (path, signal) => {
  const response = await fetch(path, { method: "GET", cache: "no-store", signal });
  const value: unknown = await response.json();
  if (!response.ok) throw new Error(object(value) && typeof value.message === "string" ? value.message : "本案声音暂不可读，请重试。");
  return value;
};

const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const positiveInteger = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const count = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const strings = (value: unknown) => Array.isArray(value) && value.every(entry => typeof entry === "string");
const records = (value: unknown) => Array.isArray(value) && value.every(object);
const reference = (value: unknown) => object(value) && typeof value.type === "string" && typeof value.id === "string" && positiveInteger(value.version);
const available = (value: Record<string, unknown>) => !["unavailable", "withdrawn"].includes(String(value.status));
const sources = (value: unknown) => Array.isArray(value) && value.every(entry => reference(entry) && available(entry));
const referenceMetadata = (value: unknown) => object(value) && value.type === "knowledge"
  && ["id", "version"].every(field => value[field] === undefined || typeof value[field] === "string" || typeof value[field] === "number" && Number.isSafeInteger(value[field]));

export function isProposalVoicesResponse(value: unknown, categoryId: string, document: ProposalViewDocument): value is ProposalVoicesResponse {
  if (!object(value) || value.version !== "proposal-voices/v1" || value.category_id !== categoryId || typeof value.as_of !== "string" || !object(value.document)) return false;
  const identity = value.document;
  if (typeof identity.proposal_id !== "string" || !positiveInteger(identity.revision) || typeof identity.document_digest !== "string" || !identity.document_digest
    || !(identity.submission_id === null || typeof identity.submission_id === "string") || typeof identity.document_mode !== "string"
    || !matchesProposalDocument(identity as ProposalViewDocument, document)) return false;
  return Array.isArray(value.entries) && value.entries.every(entry => object(entry)
    && ["knowledge_id", "lineage_id", "label", "source_platform", "origin", "status"].every(field => typeof entry[field] === "string")
    && available(entry) && positiveInteger(entry.version) && (entry.current_version === null || positiveInteger(entry.current_version))
    && (entry.sample_size === null || count(entry.sample_size)) && sources(entry.source_refs) && sources(entry.representative_refs)
    && typeof entry.used_in_context === "boolean" && records(entry.source_changes) && (entry.source_changes as Record<string, unknown>[]).every(available)
    && Array.isArray(entry.related_items) && entry.related_items.every(item => object(item) && typeof item.item_id === "string" && positiveInteger(item.version) && typeof item.kind === "string" && typeof item.label === "string"))
    && Array.isArray(value.unavailable) && value.unavailable.every(entry => object(entry) && referenceMetadata(entry.reference) && strings(entry.reasons))
    && object(value.counts) && count(value.counts.entries) && count(value.counts.unavailable_entries)
    && value.counts.entries === value.entries.length && value.counts.unavailable_entries === value.unavailable.length;
}

/** Only an explicit readable quote is a quotation; a voice label is never one. */
export function proposalVoiceQuotes(entry: ProposalVoiceEntry): (ProposalViewSource & { quote: string })[] {
  const quotes = new Map<string, ProposalViewSource & { quote: string }>();
  for (const source of [...entry.representative_refs, ...entry.source_refs]) {
    if (typeof source.quote !== "string" || !source.quote.trim() || ["unavailable", "withdrawn"].includes(String(source.status))) continue;
    const key = JSON.stringify([source.type, source.id, source.version, source.line, source.quote]);
    quotes.set(key, { ...source, quote: source.quote });
  }
  return [...quotes.values()];
}
