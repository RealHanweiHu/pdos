"use client";

import { Button } from "@/components/ui/button";

type Reference = { quote: string };
export type VerificationPreparationItem = {
  id: string;
  feature?: string | null;
  sample_count?: number | null;
  method?: Reference | null;
  criterion?: { lower?: string | null; upper?: string | null; source: Reference } | null;
  criterion_text?: string | null;
  criterion_source?: Reference | null;
  unit?: string | null;
};
type NamedVersion = { id: string; name: string; revision: number };
export type VerificationPreparationTarget = NamedVersion & {
  engineering_configuration: NamedVersion;
  manufacturing_configuration: NamedVersion;
};
export type SavedVerificationPreparation = {
  receipt_id: string;
  preparation_id: string;
  expected_preparation_revision: number;
  preparation_sha256: string;
};
export type VerificationPreparationCardProps = {
  title: string;
  purpose: string;
  target: VerificationPreparationTarget;
  items: readonly VerificationPreparationItem[];
  basisCount: number | null;
  busy?: boolean;
  disabled?: boolean;
} & ({
  state: "pending";
  onPreview: (trigger: HTMLButtonElement) => void;
} | {
  state: "adopted";
  preparation: SavedVerificationPreparation;
  onCreateRequest: (preparation: SavedVerificationPreparation, trigger: HTMLButtonElement) => void;
});

function criterion(item: VerificationPreparationItem) {
  if (item.criterion) {
    const { lower, upper } = item.criterion;
    const bounds = [lower != null ? `≥ ${lower}` : "", upper != null ? `≤ ${upper}` : ""].filter(Boolean);
    if (bounds.length) return `${bounds.join("，")}${item.unit ? ` ${item.unit}` : ""}`;
  }
  return item.criterion_source ? item.criterion_text?.trim() || "待确认" : "待确认";
}

/** Display values are resolved by the parent from the checked candidate and actual target. */
export function VerificationPreparationCard(props: VerificationPreparationCardProps) {
  const { title, purpose, target, items, basisCount, busy, disabled } = props;
  const unavailable = !!busy || !!disabled;
  return <article aria-label="复验准备" className="min-w-0 space-y-3 rounded-lg border border-border bg-card p-3 text-card-foreground [overflow-wrap:anywhere]" aria-busy={busy || undefined}>
    <header className="min-w-0 space-y-1">
      <p className="text-xs text-muted-foreground">{props.state === "adopted" ? `复验准备 · 已保存 v${props.preparation.expected_preparation_revision}` : "复验准备 · 待确认"}</p>
      <h4 className="font-medium">{title.trim() || "复验准备"}</h4>
      <p className="whitespace-pre-wrap text-sm">{purpose.trim() || "复验目的待确认"}</p>
    </header>
    <dl className="grid min-w-0 gap-2 text-sm sm:grid-cols-3">
      {([
        ["Build", target],
        ["工程配置", target.engineering_configuration],
        ["制造配置", target.manufacturing_configuration],
      ] as const).map(([label, value]) => <div key={label} className="min-w-0">
        <dt className="text-xs text-muted-foreground">{label}</dt>
        <dd>{value.name} · v{value.revision}</dd>
      </div>)}
    </dl>
    {items.length ? <ul aria-label="测试项" className="space-y-2">
      {items.map(item => <li key={item.id} className="min-w-0 space-y-1 border-t border-border pt-2 text-sm">
        <p className="font-medium">{item.feature?.trim() || "测试项待确认"}</p>
        <dl className="grid min-w-0 gap-1">
          <div className="flex min-w-0 gap-2"><dt className="shrink-0 text-muted-foreground">样本数</dt><dd>{Number.isSafeInteger(item.sample_count) && Number(item.sample_count) > 0 ? item.sample_count : "待确认"}</dd></div>
          <div className="flex min-w-0 gap-2"><dt className="shrink-0 text-muted-foreground">方法</dt><dd className="min-w-0 whitespace-pre-wrap">{item.method?.quote.trim() || "待确认"}</dd></div>
          <div className="flex min-w-0 gap-2"><dt className="shrink-0 text-muted-foreground">判据</dt><dd className="min-w-0 whitespace-pre-wrap">{criterion(item)}</dd></div>
        </dl>
      </li>)}
    </ul> : <p className="text-sm text-muted-foreground">测试项待确认</p>}
    <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2">
      <p className="text-xs text-muted-foreground">{Number.isSafeInteger(basisCount) && Number(basisCount) >= 0 ? `${basisCount} 条依据` : "依据待确认"}</p>
      {props.state === "pending" ? <Button type="button" variant="outline" size="sm" disabled={unavailable} onClick={event => { if (!unavailable) props.onPreview(event.currentTarget); }}>核对并预览</Button>
        : <Button type="button" variant="outline" size="sm" disabled={unavailable} onClick={event => { if (!unavailable) props.onCreateRequest(props.preparation, event.currentTarget); }}>创建复验请求</Button>}
    </footer>
  </article>;
}
