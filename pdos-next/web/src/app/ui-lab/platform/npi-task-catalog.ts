import "server-only";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { NpiTaskTemplate } from "./project-task-data";

type GuideContext = {
  projectType: string;
  phaseId: string;
  phaseCode: string;
  phaseName: string;
  taskId: string;
  taskName: string;
  description: string;
  isGate: boolean;
};
type GuideManifest = {
  deliverables: Record<
    string,
    {
      contexts: GuideContext[];
      checkItems: {
        requirement: string;
        bindings: Pick<GuideContext, "projectType" | "phaseId" | "taskId">[];
      }[];
    }
  >;
};

// Reuse the existing guide's task layer, not its individual deliverable checks.
// This preview selects one task family per project type instead of merging variants.
export async function readNpiTaskCatalog(): Promise<NpiTaskTemplate[]> {
  const manifest = JSON.parse(
    await readFile(
      resolve(
        process.cwd(),
        "../../assets/cehub/deliverable-guide-manifest.json",
      ),
      "utf8",
    ),
  ) as GuideManifest;
  const catalog = new Map<string, NpiTaskTemplate>();
  for (const [deliverable, entry] of Object.entries(manifest.deliverables)) {
    for (const context of entry.contexts) {
      const selected =
        (context.projectType === "npd" &&
          /^(p[1-7]|d[1-8]|e[1-7]|v[1-8]|pv[1-8]|mp[1-6])$/.test(
            context.taskId,
          )) ||
        (context.projectType === "derivative" &&
          context.taskId.startsWith("drv_"));
      if (!selected) continue;
      const key = `${context.projectType}:${context.phaseId}:${context.taskId}`;
      let task = catalog.get(key);
      if (!task) {
        task = {
          key,
          projectType: context.projectType,
          phase: context.phaseName,
          phaseCode: context.phaseCode,
          taskId: context.taskId,
          title: context.taskName.replace(/\s*\(Gate\s+\d+\)/gi, "").trim(),
          originalTitle: context.taskName,
          description: context.description,
          deliverables: [],
          requirements: [],
          isGate: context.isGate,
        };
        catalog.set(key, task);
      }
      if (!task.deliverables.includes(deliverable))
        task.deliverables.push(deliverable);
      for (const check of entry.checkItems) {
        if (
          check.bindings.some(
            (binding) =>
              binding.projectType === context.projectType &&
              binding.phaseId === context.phaseId &&
              binding.taskId === context.taskId,
          ) &&
          !task.requirements.includes(check.requirement)
        ) {
          task.requirements.push(check.requirement);
        }
      }
    }
  }
  return [...catalog.values()].sort(
    (a, b) =>
      a.phaseCode.localeCompare(b.phaseCode, undefined, { numeric: true }) ||
      a.taskId.localeCompare(b.taskId, undefined, { numeric: true }),
  );
}
