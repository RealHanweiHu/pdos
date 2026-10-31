"use client";

import { useEffect, useRef, useState } from "react";
import { VerificationPreparationCard, type SavedVerificationPreparation, type VerificationPreparationItem } from "./verification-preparation-card";
import { Button } from "@/components/ui/button";
import { verificationPreparationCandidate, type DomainCandidate } from "@/lib/domain-candidate";
import { readProjectBuilds, type ProjectBuildRecord } from "@/lib/project-build-summary";
import { normalizeProfessional, type ProfessionalPreparation, type ProfessionalRequest } from "@/lib/verification-professional";
import { projectWorkspaceHref } from "@/lib/project-workspace-navigation";
import type { WorkspaceTransport } from "@/lib/workspace-api";

type Props = {
  api: WorkspaceTransport; categoryId: string; candidate: DomainCandidate; disabled?: boolean; readVersion: number;
  onPreview: (trigger: HTMLButtonElement) => void;
  onCreate: (preparation: ProfessionalPreparation, product: { id: string; revision: number }, trigger: HTMLButtonElement) => void;
  onRequestRead: (request: ProfessionalRequest) => void;
  onUnavailable?: () => void; pendingRequestId?: string;
};
export function VerificationPreparationCandidate(props: Props) {
  if (!verificationPreparationCandidate(props.candidate)) return <p role="alert">复验准备暂不可核对，请刷新。</p>;
  return <Candidate key={`${props.candidate.event_id}:${props.candidate.state}:${props.readVersion}`} {...props}/>;
}
function Candidate({ api, categoryId, candidate, disabled, onPreview, onCreate, onRequestRead, onUnavailable, pendingRequestId }: Props) {
  const target = candidate.target!, command = candidate.command!;
  const [reading, setReading] = useState<{ build: ProjectBuildRecord; preparation: ProfessionalPreparation | null; product: { id: string; revision: number } | null; request: ProfessionalRequest | null } | null>(null);
  const [error, setError] = useState(""), [attempt, setAttempt] = useState(0);
  const preferredRequest = useRef(pendingRequestId);
  const callbacks = useRef({ onRequestRead, onUnavailable });
  useEffect(() => { callbacks.current = { onRequestRead, onUnavailable }; }, [onRequestRead, onUnavailable]);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      setReading(null); setError("");
      try {
        const builds = await readProjectBuilds(api, { categoryId, productId: target.product_id, projectId: target.project_id });
        const build = builds.items.find(row => row.id === target.id && row.revision === target.revision
          && row.engineering_configuration.id === target.engineering_configuration.id && row.engineering_configuration.revision === target.engineering_configuration.revision
          && row.manufacturing_configuration.id === target.manufacturing_configuration.id && row.manufacturing_configuration.revision === target.manufacturing_configuration.revision);
        if (!build) throw new Error("原Build或配置已变化，请刷新候选。");
        let preparation: ProfessionalPreparation | null = null, product: { id: string; revision: number } | null = null, request: ProfessionalRequest | null = null;
        if (candidate.state === "adopted") {
          const fixed = candidate.preparation;
          if (!fixed || candidate.receipt?.subject_id !== fixed.preparation_id || candidate.receipt.id !== fixed.receipt_id || candidate.receipt.operation !== "verification.preparation.record") throw new Error("保存准备的回执尚未核对，请刷新。");
          const [data, workspace] = await Promise.all([
            api<unknown>(`v1/products/${target.product_id}/verification-professional?project_id=${target.project_id}`),
            api<{ product: { id: string; revision: number } }>(`v1/products/${target.product_id}/workspace`),
          ]);
          const actual = normalizeProfessional(data, target.project_id);
          preparation = actual.preparations.find(row => row.id === fixed.preparation_id && row.revision === fixed.expected_preparation_revision && row.sha256 === fixed.preparation_sha256) ?? null;
          if (!preparation || preparation.build_id !== build.id || preparation.build_revision !== build.revision) throw new Error("实际准备版本暂不可读，请刷新。");
          if (workspace.product?.id !== target.product_id || !Number.isSafeInteger(workspace.product.revision) || workspace.product.revision < 1) throw new Error("当前型号版本暂不可核对。");
          product = workspace.product;
          const requests = actual.requests.filter(row => row.preparation_id === preparation!.id && row.preparation_revision === preparation!.revision && row.preparation_sha256 === preparation!.sha256 && row.is_current);
          request = requests.find(row => row.request_id === preferredRequest.current) ?? requests[0] ?? null;
        }
        if (active) { setReading({ build, preparation, product, request }); if (request) callbacks.current.onRequestRead(request); }
      } catch (failure) {
        if (!active) return;
        setError(failure instanceof Error ? failure.message : "复验准备暂不可读。");
        if ([401, 403].includes((failure as { status?: number }).status ?? 0)) callbacks.current.onUnavailable?.();
      }
    });
    return () => { active = false; };
  }, [api, categoryId, target, candidate, attempt]);
  if (error) return <div className="space-y-2 rounded-lg border border-border p-3"><p role="alert">{error}</p><Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => setAttempt(value => value + 1)}>重新读取准备</Button></div>;
  if (!reading) return <p role="status" className="text-sm text-muted-foreground">正在核对复验准备…</p>;
  const payload = reading.preparation?.input_snapshot ?? command.payload;
  const details = {
    title: String(payload.title ?? "复验准备"), purpose: String(payload.purpose ?? ""),
    target: { id: reading.build.id, name: reading.build.name, revision: reading.build.revision,
      engineering_configuration: reading.build.engineering_configuration, manufacturing_configuration: reading.build.manufacturing_configuration },
    items: payload.items as VerificationPreparationItem[],
    basisCount: Number.isSafeInteger(candidate.basis_count) && Number(candidate.basis_count) >= 0 ? Number(candidate.basis_count) : null,
  };
  if (candidate.state !== "adopted") return <VerificationPreparationCard {...details} state="pending" disabled={disabled} onPreview={onPreview}/>;
  const fixed = candidate.preparation as SavedVerificationPreparation;
  const href = reading.request ? `${projectWorkspaceHref(categoryId, target.product_id, target.project_id, "builds", "professional")}&build=${encodeURIComponent(target.id)}&request=${encodeURIComponent(reading.request.request_id)}` : null;
  return <div className="space-y-2"><VerificationPreparationCard {...details} state="adopted" preparation={fixed} disabled={disabled || !!reading.request || reading.preparation?.capabilities.request_create !== true || reading.preparation?.source_status !== "current"} onCreateRequest={(_fixed, trigger) => { if (reading.preparation && reading.product) onCreate(reading.preparation, reading.product, trigger); }}/>
    {href && <a className="text-sm underline underline-offset-4" href={href}>打开复验请求</a>}
    {!reading.request && (reading.preparation?.capabilities.request_create !== true || reading.preparation?.source_status !== "current") && <p className="text-xs text-muted-foreground">当前暂不能创建请求，可刷新后再核对。</p>}
  </div>;
}
