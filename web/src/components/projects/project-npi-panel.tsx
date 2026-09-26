"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { SpecVerificationCoverage } from "./spec-verification-coverage";
import { TestExecutionPreparation } from "./test-execution-preparation";
import { TestVerificationPath } from "./test-verification-path";
import { ProjectBuildCreate } from "./project-build-create";
import { BuildMaterials } from "./build-materials";
import { ProjectTestImport } from "./project-test-import";
import { TestImportHistory } from "./test-import-history";
import { ProjectTestConversation } from "./project-test-conversation";
import { ProjectTestTemplate, TestCoverageView } from "./project-test-template";
import { ProjectTestRuns } from "./project-test-runs";
import { ProjectConfigurationComparison } from "./project-configuration-comparison";
import { ProjectFirmwareWorkPackages } from "./project-firmware-work-packages";

import {
  addSample,
  BUILD_PURPOSE_LABELS,
  fetchNpiSnapshot,
  NpiRequestError,
  updateBuild,
} from "./project-npi-api";
import {
  BUILD_PHASE_LABELS,
  BUILD_STATUS_LABELS,
  EMPTY_NPI_SNAPSHOT,
  labelFor,
  SAMPLE_STATUS_LABELS,
  TEST_CASE_STATUS_LABELS,
  type NpiSnapshot,
} from "./project-npi-types";

type LoadState = "loading" | "ready" | "error";

type Props = {
  projectId: string;
  canEdit: boolean;
  canRecordTests?: boolean;
  /** Build material demand, allocation and movements follow product-engineering edit rights. */
  canEditMaterials?: boolean;
};

/**
 * The Build → Sample → Test operating surface.
 *
 * This chain existed in the backend since V1 but had no UI at all, so the
 * digital thread the Gate panel points at ("查看产品工程") led nowhere. Every
 * action here writes through the NPI BFF; nothing is computed client-side.
 */
export function ProjectNpiPanel({ projectId, canEdit, canRecordTests = canEdit, canEditMaterials = canEdit }: Props) {
  const [snapshot, setSnapshot] = useState<NpiSnapshot>(EMPTY_NPI_SNAPSHOT);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const search = useSearchParams();
  const targetBuild = search.get("build_id");
  const buildScope = `${projectId}:${targetBuild ?? ""}`;
  const [buildSelection, setBuildSelection] = useState<{ scope: string; id: string | null } | null>(null);
  const openBuildId = buildSelection?.scope === buildScope ? buildSelection.id : targetBuild;
  const setOpenBuildId = (id: string | null) => setBuildSelection({ scope: buildScope, id });
  useEffect(() => {
    if (state === "ready" && targetBuild) document.getElementById(`build-${targetBuild}`)?.scrollIntoView({ block: "start" });
  }, [state, targetBuild]);
  const [serialDraft, setSerialDraft] = useState("");

  const load = useCallback(async () => {
    setState("loading");
    setError(null);
    try {
      setSnapshot(await fetchNpiSnapshot(projectId));
      setState("ready");
    } catch (failure) {
      setError(
        failure instanceof NpiRequestError ? failure.message : "试制与测试数据暂不可用",
      );
      setState("error");
    }
  }, [projectId]);

  // The initial fetch is done inside the effect rather than by calling `load`,
  // so no state is set synchronously during the effect body. The cancelled
  // flag matters on its own: switching projects mid-flight must not let the
  // previous project's snapshot land in this one's panel.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const next = await fetchNpiSnapshot(projectId);
        if (cancelled) return;
        setSnapshot(next);
        setState("ready");
      } catch (failure) {
        if (cancelled) return;
        setError(
          failure instanceof NpiRequestError ? failure.message : "试制与测试数据暂不可用",
        );
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const refreshImportResults = useCallback(async () => {
    try {
      const next = await fetchNpiSnapshot(projectId);
      setSnapshot(next);
      setError(null);
    } catch {
      setError("批次已处理，但测试概览刷新失败，请刷新页面。");
    }
  }, [projectId]);

  const act = useCallback(
    async (operation: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await operation();
        await load();
      } catch (failure) {
        setError(
          failure instanceof NpiRequestError ? failure.message : "操作失败，请重试",
        );
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">正在加载试制与测试…</p>;
  }

  if (state === "error") {
    return (
      <div className="space-y-3">
        <p className="text-sm text-destructive">{error}</p>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          重试
        </Button>
      </div>
    );
  }

  const samplesByBuild = new Map<string, typeof snapshot.samples>();
  for (const sample of snapshot.samples) {
    const bucket = samplesByBuild.get(sample.build_batch_id) ?? [];
    bucket.push(sample);
    samplesByBuild.set(sample.build_batch_id, bucket);
  }

  const casesByPlan = new Map<string, typeof snapshot.test_cases>();
  for (const testCase of snapshot.test_cases) {
    const bucket = casesByPlan.get(testCase.plan_id) ?? [];
    bucket.push(testCase);
    casesByPlan.set(testCase.plan_id, bucket);
  }

  return (
    <div className="space-y-8" data-testid="npi-panel">
      {error ? <p className="text-sm text-destructive">{error}</p> : null}

      <SpecVerificationCoverage key={`spec-coverage:${projectId}`} projectId={projectId} />
      <ProjectFirmwareWorkPackages key={`firmware-work:${projectId}`} projectId={projectId} canEdit={canEdit} canRecordResults={canRecordTests} />

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">试制批次与样机</h3>
        {canEdit && <ProjectBuildCreate key={projectId} projectId={projectId} busy={busy} onCreated={refreshImportResults} />}
        {snapshot.builds.length === 0 ? (
          <p className="text-sm text-muted-foreground">尚无试制批次。</p>
        ) : (
          <ul className="space-y-3">
            {snapshot.builds.map((build) => {
              const samples = samplesByBuild.get(build.id) ?? [];
              const open = openBuildId === build.id;
              return (
                <li id={`build-${build.id}`} key={build.id} className="scroll-mt-4 rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{build.code}</span>
                    <span className="text-xs text-muted-foreground">
                      {labelFor(BUILD_PHASE_LABELS, build.phase)} ·{" "}
                      {labelFor(BUILD_STATUS_LABELS, build.status)} · 计划{" "}
                      {build.planned_quantity} 台 · 样机 {samples.length} 台
                      {build.purpose && ` · ${labelFor(BUILD_PURPOSE_LABELS, build.purpose)}`}
                    </span>
                    <span className="ml-auto flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setOpenBuildId(open ? null : build.id)}
                      >
                        {open ? "收起样机" : "展开样机"}
                      </Button>
                      {canEdit && build.status === "planned" ? (
                        <Button
                          size="sm"
                          disabled={busy}
                          onClick={() =>
                            void act(() =>
                              updateBuild(projectId, build.id, {
                                status: "in_progress",
                                completed_quantity: 0,
                              }),
                            )
                          }
                        >
                          开始试制
                        </Button>
                      ) : null}
                      {canEdit && build.status === "in_progress" ? (
                        <Button
                          size="sm"
                          disabled={busy}
                          onClick={() =>
                            void act(() =>
                              updateBuild(projectId, build.id, {
                                status: "completed",
                                completed_quantity: samples.length,
                              }),
                            )
                          }
                        >
                          完成试制
                        </Button>
                      ) : null}
                    </span>
                  </div>

                  {open ? (
                    <div className="mt-3 space-y-2 border-t pt-3">
                      {samples.length === 0 ? (
                        <p className="text-sm text-muted-foreground">该批次尚无样机。</p>
                      ) : (
                        <ul className="space-y-1">
                          {samples.map((sample) => (
                            <li key={sample.id} className="text-sm">
                              <span className="font-mono">{sample.serial_number}</span>
                              <span className="ml-2 text-xs text-muted-foreground">
                                {labelFor(SAMPLE_STATUS_LABELS, sample.status)}
                              </span>
                            </li>
                          ))}
                        </ul>
                      )}
                      <BuildMaterials projectId={projectId} buildId={build.id} canEdit={canEditMaterials} />
                      {canEdit ? (
                        <div className="flex gap-2 pt-1">
                          <input
                            aria-label={`${build.code} 样机编号`}
                            className="h-9 flex-1 rounded-md border px-2 text-sm"
                            placeholder="样机编号，例如 SN-1001"
                            value={serialDraft}
                            onChange={(event) => setSerialDraft(event.target.value)}
                          />
                          <Button
                            size="sm"
                            disabled={busy || !serialDraft.trim()}
                            onClick={() =>
                              void act(async () => {
                                await addSample(projectId, build.id, {
                                  serial_number: serialDraft.trim(),
                                });
                                setSerialDraft("");
                              })
                            }
                          >
                            登记样机
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <ProjectConfigurationComparison key={projectId} projectId={projectId} samples={snapshot.samples} canEdit={canEdit} />

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">测试计划与用例</h3>
        {canEdit && <ProjectTestTemplate key={projectId} projectId={projectId} onSaved={load} />}
        {snapshot.test_plans.length === 0 ? (
          <p className="text-sm text-muted-foreground">尚无测试计划。</p>
        ) : (
          <ul className="space-y-3">
            {snapshot.test_plans.map((plan) => {
              const cases = casesByPlan.get(plan.id) ?? [];
              return (
                <li key={plan.id} className="rounded-md border p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{plan.title}</span>
                    <span className="text-xs text-muted-foreground">
                      {labelFor(BUILD_PHASE_LABELS, plan.phase)} · 用例 {cases.length} 条
                    </span>
                  </div>
                  <TestCoverageView coverage={plan.coverage} />
                  {canEdit && <ProjectTestImport key={`import:${projectId}:${plan.id}`} projectId={projectId} planId={plan.id} onImported={refreshImportResults} />}
                  {canEdit && plan.coverage?.status === "configured" && !snapshot.test_plans.some((p) => p.parent_plan_id === plan.id) && <ProjectTestConversation key={`${projectId}:${plan.id}`} projectId={projectId} planId={plan.id} />}
                  {plan.parent_plan_id ? <p className="text-xs text-muted-foreground">计划修订 v{plan.template_snapshot?.plan_revision ?? 2} · 原报告与结果保留在上一版</p> : null}
                  {canEdit && cases.length === 0 && plan.status !== "completed" && plan.coverage?.status !== "configured" && (
                    <ProjectTestTemplate key={`${projectId}:${plan.id}`} projectId={projectId} planId={plan.id} onSaved={load} />
                  )}
                  <TestImportHistory key={`imports:${projectId}:${plan.id}`} projectId={projectId} planId={plan.id} onConfirmed={refreshImportResults} />
                  {cases.length > 0 ? (
                    <ul className="mt-2 space-y-1 border-t pt-2">
                      {cases.map((testCase) => (
                        <li
                          key={testCase.id}
                          className="flex flex-wrap items-center gap-2 text-sm"
                        >
                          <span>{testCase.title}</span>
                          <span className="text-xs text-muted-foreground">
                            {labelFor(TEST_CASE_STATUS_LABELS, testCase.status)}
                          </span>
                          <TestVerificationPath projectId={projectId} caseId={testCase.id} canEdit={canEdit} onSaved={refreshImportResults} />
                          <TestExecutionPreparation key={`prep:${testCase.id}`} projectId={projectId} caseId={testCase.id} canEdit={canEdit} onSaved={refreshImportResults} />
                          <ProjectTestRuns
                            key={`${projectId}:${testCase.id}`}
                            projectId={projectId}
                            testCaseId={testCase.id}
                            canRecord={canRecordTests}
                            samples={snapshot.samples}
                            onChanged={refreshImportResults}
                          />
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      {snapshot.sample_signoffs.length > 0 ? (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold">样机会签</h3>
          <ul className="space-y-1">
            {snapshot.sample_signoffs.map((signoff) => (
              <li key={signoff.id} className="text-sm">
                {signoff.audience} · {signoff.status} · 样机 {signoff.sample_ids.length} 台
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
