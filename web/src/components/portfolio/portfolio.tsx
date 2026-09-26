"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { requestProjects } from "@/components/projects/project-api";
import type { Project } from "@/components/projects/project-types";
import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { cn } from "@/lib/utils";
import { PortfolioMilestones } from "./portfolio-milestones";
import { ExecutiveBriefPreparation } from "./executive-brief-preparation";
import { PortfolioProgress } from "./portfolio-progress";
import { PortfolioControlQueue } from "./portfolio-control-queue";
import { PortfolioProductPipeline } from "./portfolio-product-pipeline";
import { PortfolioSuppliers } from "./portfolio-suppliers";
import { PortfolioResources } from "./portfolio-resources";
import { PortfolioMaterials } from "./portfolio-materials";
import { PortfolioHealth } from "./portfolio-health";
import { PortfolioComparisons } from "./portfolio-comparisons";

type LoadState = "loading" | "ready" | "error" | "redirecting";

const statusLabels: Record<Project["status"], string> = {
  draft: "草稿",
  proposed: "已提交",
  approved: "已批准",
  active: "进行中",
  on_hold: "暂停",
  completed: "已完成",
  archived: "已归档",
};

/** Days until the target date; negative means overdue. Null when unset. */
function daysToTarget(project: Project, today: Date): number | null {
  if (project.target_date === null) return null;
  const target = new Date(`${project.target_date}T00:00:00Z`);
  const start = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  return Math.round((target.getTime() - start) / 86_400_000);
}

export function Portfolio() {
  const { replace } = useRouter();
  const [state, setState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loggingOut, setLoggingOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const loaded = await requestProjects();
        if (!active) return;
        if (loaded === null) {
          setState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(loaded.identity);
        setProjects(loaded.projects);
        setState("ready");
      } catch (loadError) {
        if (!active) return;
        setError(loadError instanceof Error ? loadError.message : "项目组合暂不可用");
        setState("error");
      }
    })();
    return () => {
      active = false;
    };
  }, [replace]);

  const rows = useMemo(() => {
    const today = new Date();
    return projects
      .map((project) => ({ project, remaining: daysToTarget(project, today) }))
      .sort((left, right) => {
        // Soonest deadline first; projects without one sink to the bottom.
        if (left.remaining === null && right.remaining === null) {
          return left.project.code.localeCompare(right.project.code);
        }
        if (left.remaining === null) return 1;
        if (right.remaining === null) return -1;
        return left.remaining - right.remaining;
      });
  }, [projects]);

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      replace("/login");
    }
  }

  if (state === "redirecting") return null;
  if (state === "loading") {
    return (
      <main aria-busy="true" className="mx-auto max-w-6xl px-4 py-10 text-sm text-muted-foreground">
        正在加载项目组合…
      </main>
    );
  }
  if (state === "error" || identity === null) {
    return (
      <main className="mx-auto flex min-h-svh max-w-md flex-col items-center justify-center px-6 text-center">
        <h1 className="text-lg font-semibold">项目组合暂不可用</h1>
        <p className="mt-1 text-sm text-muted-foreground">{error ?? "无法读取项目列表。"}</p>
      </main>
    );
  }

  const overdue = rows.filter((row) => row.remaining !== null && row.remaining < 0).length;

  return (
    <WorkspaceShell
      active="portfolio"
      identity={identity}
      loggingOut={loggingOut}
      onLogout={() => void logout()}
    >
      <div className="flex flex-wrap items-end justify-between gap-4 border-b pb-4">
        <div>
          <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">
            Portfolio
          </p>
          <h1 className="mt-1 text-lg font-semibold">项目组合</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            查看各项目登记证据的六维健康、基线与预测偏差，并回到原业务记录办理。
          </p>
        </div>
        <dl className="flex overflow-hidden rounded-lg border bg-card text-center">
          <div className="min-w-24 px-3 py-2">
            <dt className="text-[10px] text-muted-foreground">项目数</dt>
            <dd className="mt-0.5 font-mono text-base font-semibold">{rows.length}</dd>
          </div>
          <div className="min-w-24 border-l px-3 py-2">
            <dt className="text-[10px] text-muted-foreground">已过目标日</dt>
            <dd
              className={cn(
                "mt-0.5 font-mono text-base font-semibold",
                overdue > 0 && "text-destructive",
              )}
            >
              {overdue}
            </dd>
          </div>
        </dl>
      </div>

      <ExecutiveBriefPreparation projects={projects}/>
        <PortfolioProgress />
      <PortfolioMilestones projects={projects} />
      <PortfolioControlQueue projects={projects} />
      <PortfolioProductPipeline />
      <PortfolioMaterials />
      <PortfolioSuppliers projects={projects}/>
      <PortfolioResources />
      <PortfolioHealth />
      <PortfolioComparisons projects={projects} />

      {rows.length === 0 ? (
        <section
          className="mt-5 rounded-lg border border-dashed bg-card px-6 py-10 text-center"
          role="status"
        >
          <h2 className="font-semibold">还没有可见的项目</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            列表为空表示你尚未加入任何项目，而不是数据读取失败。
          </p>
        </section>
      ) : (
        <details className="mt-5 rounded-lg border bg-card p-3">
          <summary className="cursor-pointer text-sm font-medium">项目登记信息与目标日</summary>
          <p className="my-2 text-xs text-muted-foreground">登记目标日仅供查阅；当前延期判断见上方正式基线与预测对照。</p>
          <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-sm">
            <caption className="sr-only">项目登记信息</caption>
            <thead>
              <tr className="border-b text-xs text-muted-foreground">
                <th className="px-3 py-2 font-medium" scope="col">
                  项目
                </th>
                <th className="px-3 py-2 font-medium" scope="col">
                  当前阶段
                </th>
                <th className="px-3 py-2 font-medium" scope="col">
                  状态
                </th>
                <th className="px-3 py-2 font-medium" scope="col">
                  目标日期
                </th>
                <th className="px-3 py-2 font-medium" scope="col">
                  倒计时
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ project, remaining }) => (
                <tr className="border-b last:border-b-0" key={project.id}>
                  <td className="px-3 py-2">
                    <Link
                      className="font-medium text-primary hover:underline"
                      href={`/projects?project=${project.id}&tab=overview`}
                    >
                      {project.code} · {project.name}
                    </Link>
                  </td>
                  <td className="px-3 py-2">{project.current_stage.name}</td>
                  <td className="px-3 py-2">{statusLabels[project.status]}</td>
                  <td className="px-3 py-2 font-mono text-xs">{project.target_date ?? "—"}</td>
                  <td
                    className={cn(
                      "px-3 py-2 font-mono text-xs",
                      remaining !== null && remaining < 0 && "font-semibold text-destructive",
                    )}
                  >
                    {remaining === null
                      ? "—"
                      : remaining < 0
                        ? `目标日已过 ${Math.abs(remaining)} 天`
                        : `剩余 ${remaining} 天`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </details>
      )}
    </WorkspaceShell>
  );
}
