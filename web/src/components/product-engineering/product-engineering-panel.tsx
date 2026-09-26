"use client";

import { useEffect } from "react";
import { DatabaseIcon, LinkSimpleIcon } from "@phosphor-icons/react/ssr";

import { ContextKnowledge } from "@/components/knowledge/context-knowledge";

import { DevelopmentBomForm } from "./development-bom-form";
import { ProductEngineeringError, ProductEngineeringLoading } from "./product-engineering-state";
import { SpecificationForm } from "./specification-form";
import type {
  DevelopmentBomCreateInput,
  DevelopmentBomType,
  ProductEngineeringRegister,
  SpecificationCreateInput,
} from "./product-engineering-types";

export type ProductEngineeringLoadState = "error" | "idle" | "loading" | "ready";

const bomTypeLabels: Record<DevelopmentBomType, string> = {
  ebom: "EBOM",
  prototype: "Prototype BOM",
  cost: "Cost BOM",
};

const referenceTypeLabels = {
  mbom: "MBOM",
  routing: "Routing",
  production_version: "Production Version",
};

export function ProductEngineeringPanel({
  busy,
  canEdit,
  error,
  loadState,
  onCreateBom,
  onCreateSpecification,
  onRetry,
  register,
  status,
}: {
  busy: boolean;
  canEdit: boolean;
  error: string | null;
  loadState: ProductEngineeringLoadState;
  onCreateBom: (input: DevelopmentBomCreateInput) => Promise<boolean>;
  onCreateSpecification: (input: SpecificationCreateInput) => Promise<boolean>;
  onRetry: () => void;
  register: ProductEngineeringRegister | null;
  status: string | null;
}) {
  useEffect(() => {
    if (loadState !== "ready" || !register) return;
    const anchor = window.location.hash.slice(1);
    if (register.specifications.some(item => anchor === `spec-${item.id}`) || register.boms.some(item => anchor === `bom-${item.id}`)) {
      document.getElementById(anchor)?.scrollIntoView({ block: "center" });
    }
  }, [loadState, register]);
  if (loadState === "idle" || loadState === "loading") return <ProductEngineeringLoading />;
  if (loadState === "error" || register === null) {
    return <ProductEngineeringError onRetry={onRetry} />;
  }

  return (
    <div className="space-y-4">
      <header className="rounded-lg border bg-card p-4">
        <div className="flex items-start gap-3">
          <DatabaseIcon aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-primary" />
          <div>
            <h3 className="font-semibold">产品工程主数据</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              PDOS 维护 Specification、EBOM、Prototype BOM 与 Cost BOM；MBOM、Routing、Production Version 仅保存 ERP 引用。
            </p>
          </div>
        </div>
      </header>

      {status ? <p className="rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success" role="status">{status}</p> : null}
      {error ? <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{error}</p> : null}

      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <section aria-label="产品规格" className="min-w-0 overflow-hidden rounded-lg border bg-card">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h3 className="font-semibold">产品规格</h3>
            <span className="font-mono text-xs text-muted-foreground">{register.specifications.length}</span>
          </div>
          {register.specifications.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <h3 className="font-semibold">尚未建立产品规格</h3>
              <p className="mt-1 text-sm text-muted-foreground">先冻结可追溯的规格版本，再关联开发 BOM。</p>
            </div>
          ) : (
            <ul className="divide-y" role="list">
              {register.specifications.map((item) => (
                <li id={`spec-${item.id}`} className="px-4 py-3" key={item.id}>
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{item.title}</p>
                      <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{item.code}</p>
                    </div>
                    <span className="shrink-0 rounded-full border bg-muted px-2 py-1 font-mono text-[11px] text-muted-foreground">v{item.version}</span>
                  </div>
                  <a className="mt-2 block text-xs text-primary underline" href={`/projects?project=${item.project_id}&tab=overview&specification_owner_id=${item.id}`}>规格责任、原内容与版本接续</a>
                  <ContextKnowledge projectId={item.project_id} contextKind="part_selection" entityId={item.id} />
                </li>
              ))}
            </ul>
          )}
          {canEdit ? <SpecificationForm busy={busy} onSubmit={onCreateSpecification} /> : null}
        </section>

        <section aria-label="开发 BOM" className="min-w-0 overflow-hidden rounded-lg border bg-card">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h3 className="font-semibold">开发 BOM</h3>
            <span className="font-mono text-xs text-muted-foreground">{register.boms.length}</span>
          </div>
          {register.boms.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <h3 className="font-semibold">尚未建立开发 BOM</h3>
              <p className="mt-1 text-sm text-muted-foreground">三种 BOM 独立标识类型与版本，避免与 ERP 制造真值混淆。</p>
            </div>
          ) : (
            <ul className="divide-y" role="list">
              {register.boms.map((item) => (
                <li id={`bom-${item.id}`} className="px-4 py-3" key={item.id}>
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{item.name}</p>
                      <p className="mt-1 truncate font-mono text-xs text-muted-foreground">{item.code} · v{item.version}</p>
                    </div>
                    <span className="shrink-0 rounded-full border border-primary/25 bg-primary/8 px-2 py-1 text-[11px] font-medium text-primary">{bomTypeLabels[item.bom_type]}</span>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">{item.items.length} 个条目</p>
                </li>
              ))}
            </ul>
          )}
          {canEdit ? (
            <DevelopmentBomForm
              busy={busy}
              onSubmit={onCreateBom}
              specifications={register.specifications}
            />
          ) : null}
        </section>
      </div>

      <section aria-label="ERP 制造引用" className="overflow-hidden rounded-lg border bg-card">
        <div className="flex items-center gap-2 border-b px-4 py-3">
          <LinkSimpleIcon aria-hidden="true" className="size-4 text-primary" />
          <h3 className="font-semibold">ERP 制造引用</h3>
          <span className="ml-auto font-mono text-xs text-muted-foreground">{register.erpReferences.length}</span>
        </div>
        {register.erpReferences.length === 0 ? (
          <p className="px-4 py-6 text-sm text-muted-foreground">暂无 MBOM、Routing 或 Production Version 引用。</p>
        ) : (
          <ul className="divide-y" role="list">
            {register.erpReferences.map((item) => (
              <li className="grid gap-1 px-4 py-3 text-sm sm:grid-cols-[160px_minmax(0,1fr)_auto] sm:items-center sm:gap-3" key={item.id}>
                <span className="font-medium">{referenceTypeLabels[item.reference_type]}</span>
                <span className="truncate font-mono text-xs text-muted-foreground">{item.external_id}</span>
                <span className="text-xs text-muted-foreground">{item.source_system}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
