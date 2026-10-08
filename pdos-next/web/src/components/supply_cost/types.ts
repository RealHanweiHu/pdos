/** Display DTOs only. The server owns scope, canonical sources, qualification and writes. */
export type DecimalString = string;
export type Readiness = boolean | null;
export type Freshness = "current" | "requires_recalculation" | "historical";
export type SourceRef = {
  source_id: string;
  version: string;
  sha256: string;
  captured_at: string;
  state: "current" | "stale" | "withdrawn" | "unknown";
  valid_until: string | null;
};
export type CalculationIssue = { code: string; path: string; message: string; kind: string };
export type PoolKey = { source_system: string; pool_id: string; material_id: string };
export type BasisView = {
  build: { build_id: string; ref: SourceRef; quantity: DecimalString | null; product_unit: string | null };
  bom: { ref: SourceRef; engineering_configuration: SourceRef };
};
export type BasisBindingView = {
  basis_sha256: string;
  demand_sha256: string;
  basis: BasisView;
  manufacturing_configuration: SourceRef;
};
export type ProjectionRecord<T> = {
  id: string;
  revision: string;
  created_at: string;
  freshness: Freshness;
  freshness_reasons: string[];
  result: T;
};
export type ReadState = {
  status?: "ready" | "loading" | "unconnected";
  error?: string | null;
  onRetry?: () => void | Promise<void>;
};

export type SupplyRecordKind = "commitment" | "in_transit" | "receipt" | "inventory" | "restriction";
export type SupplyDraft = {
  record_kind: SupplyRecordKind;
  record_id: string;
  material_id: string;
  quantity: DecimalString | null;
  unit: string | null;
  source_id: string;
  source_revision: string;
  pool_id?: string;
  quality: "released" | "frozen" | "unknown";
  availability: "available" | "unavailable" | "unknown";
  note: string;
};
export type SourceChoice = { ref: SourceRef; title: string };
export type MaterialChoice = { id: string; title: string; unit: string | null };
export type PoolChoice = { key: PoolKey; title: string };
export type SupplyPreviewChange = { field: string; label: string; before: string | null; after: string | null };
export type SupplyEntryPreview = {
  review_id: string;
  confirmation_token: string;
  binding_sha256: string;
  expires_at: string;
  allowed_to_confirm: boolean;
  basis_binding: BasisBindingView;
  source: SourceRef;
  record: SupplyDraft;
  changes: SupplyPreviewChange[];
  warnings: string[];
};
export type SupplyConfirmation = Pick<SupplyEntryPreview, "review_id" | "confirmation_token" | "binding_sha256">;
export type SupplyEntryReceipt = {
  receipt_id: string;
  review_id: string;
  status: "persisted";
  snapshot_id: string;
  snapshot_revision: string;
};
export type SupplyEntryPort = {
  prepare: (draft: SupplyDraft) => Promise<SupplyEntryPreview>;
  confirm: (confirmation: SupplyConfirmation) => Promise<SupplyEntryReceipt>;
  resolve?: (confirmation: SupplyConfirmation) => Promise<SupplyEntryReceipt | null>;
};
export type SupplyRecordView = SupplyDraft & {
  source: SourceRef;
  /** Receipt rows carry the actual received_at; other rows carry source capture time. */
  recorded_at: string;
  supplier_id?: string;
  expected_at?: string | null;
  commitment_id?: string | null;
};
export type SupplyPoolView = {
  key: PoolKey;
  ref: SourceRef;
  stage: "commitment" | "in_transit" | "on_hand" | "received";
  quantity: DecimalString | null;
  unit: string | null;
  availability: SupplyDraft["availability"];
  quality: SupplyDraft["quality"];
  expected_at: string | null;
};
export type ReservationView = {
  reservation_id: string;
  ref: SourceRef;
  pool: PoolKey;
  build_id: string;
  bom_item_id: string | null;
  quantity: DecimalString | null;
  unit: string | null;
};
export type SnapshotDelta = {
  record_key: string;
  field: string;
  before: string | null;
  after: string | null;
  difference: DecimalString | null;
  unit: string | null;
};
export type SnapshotReconciliation = {
  id: string;
  before_snapshot_id: string;
  before_revision: string;
  before_sha256: string;
  after_snapshot_id: string;
  after_revision: string;
  after_sha256: string;
  deltas: SnapshotDelta[];
  reasons: string[];
};
export type SupplySnapshotView = {
  id: string;
  revision: string;
  sha256: string;
  captured_at: string;
  freshness: Freshness;
  freshness_reasons: string[];
  binding: BasisBindingView;
  source_refs: SourceRef[];
  scope_complete: boolean;
  records: SupplyRecordView[];
  pools: SupplyPoolView[];
  reservations: ReservationView[];
  reconciliation: SnapshotReconciliation | null;
};

export type SupplyUseView = {
  pool: PoolKey;
  quantity_in_pool_unit: DecimalString;
  quantity_in_demand_unit: DecimalString;
  kind: "secured" | "unreserved_candidate";
  reservation_id: string | null;
  qualification_id: string | null;
};
export type CoverageLineView = {
  demand: { item_id: string; material_id: string | null; unit: string | null; critical: boolean; required_quantity: DecimalString | null; issues: CalculationIssue[] };
  known_secured_quantity: DecimalString;
  known_potential_quantity: DecimalString;
  secured_gap: DecimalString | null;
  potential_gap: DecimalString | null;
  secured_ready: Readiness;
  potential_ready: Readiness;
  uses: SupplyUseView[];
  issues: CalculationIssue[];
};
export type CoverageView = {
  schema_version: "supply-coverage-result.v1";
  algorithm: "fixed-bom-shared-pool.v1";
  input_sha256: string;
  input_snapshot: { basis: BasisView; as_of: string; supply_snapshot: SourceRef; supply_scope_complete: boolean };
  secured_ready: Readiness;
  potential_ready: Readiness;
  critical_secured_ready: Readiness;
  potential_is_feasibility_proof: false;
  lines: CoverageLineView[];
  pools: { key: PoolKey; stage: string; unit: string | null; quantity: DecimalString | null; reserved_quantity: DecimalString | null; unreserved_usable_quantity: DecimalString | null; own_secured_quantity: DecimalString | null; source: SourceRef; issues: CalculationIssue[] }[];
  issues: CalculationIssue[];
};
export type CostScopeView = {
  currency: string;
  tax_basis: "exclusive" | "inclusive";
  freight_basis: "included" | "excluded";
  coverage: "materials_only" | "materials_and_process";
  rate_purpose: "spot" | "budget";
  max_rate_age_days: number;
  nre_policy: "excluded" | "separate" | "amortize";
  nre_volume: DecimalString | null;
  assumptions: string[];
};
export type PriceView = {
  price_id: string;
  subject_kind: "material" | "process" | "nre";
  subject_id: string;
  ref: SourceRef;
  stage: "estimate" | "quote";
  amount: DecimalString | null;
  price_quantity: DecimalString | null;
  unit: string | null;
  currency: string | null;
  minimum_quantity: DecimalString | null;
  maximum_quantity: DecimalString | null;
  scope_assumption: string;
};
export type CostLineView = {
  line_id: string;
  category: "material" | "process" | "nre";
  price_id: string | null;
  quantity_per_product: DecimalString | null;
  quantity_for_build: DecimalString | null;
  demand_unit: string | null;
  quantity_in_price_unit: DecimalString | null;
  original_currency: string | null;
  original_build_amount: DecimalString | null;
  rate_id: string | null;
  per_product_candidate: DecimalString | null;
  build_candidate: DecimalString | null;
  issues: CalculationIssue[];
};
export type CostView = {
  schema_version: "cost-estimate-result.v1";
  algorithm: "fixed-bom-process-decimal.v1";
  input_sha256: string;
  input_snapshot: {
    basis: BasisView;
    as_of: string;
    scope: CostScopeView;
    prices: PriceView[];
    process: { ref: SourceRef; assumption: string; operations: { operation_id: string; quantity_per_product: DecimalString | null; unit: string | null; loss_rate: DecimalString | null }[] } | null;
    rates: { rate_id: string; ref: SourceRef; from_currency: string; to_currency: string; rate: DecimalString | null; purpose: "spot" | "budget" }[];
  };
  complete_in_selected_scope: boolean;
  currency: string;
  known_build_subtotal: DecimalString;
  known_nre_subtotal: DecimalString;
  per_product_candidate: DecimalString | null;
  build_candidate: DecimalString | null;
  nre_candidate: DecimalString | null;
  including_amortized_nre: DecimalString | null;
  lines: CostLineView[];
  issues: CalculationIssue[];
  sensitive_items: CalculationIssue[];
};
