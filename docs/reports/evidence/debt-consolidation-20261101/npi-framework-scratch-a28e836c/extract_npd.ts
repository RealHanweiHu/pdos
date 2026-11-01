// Dump the old CEHub NPD v3 template variants as JSON for analysis (read-only).
import { writeFileSync } from "node:fs";
import {
  NPD_ADDON_PACKS,
  getNpdV3EffectivePhases,
} from "/Users/huhanwei/Desktop/ce-project-hub/shared/npd-v3";
import { NPD_PHASES, NPD_PHASES_CURRENT } from "/Users/huhanwei/Desktop/ce-project-hub/shared/sop-templates";

const out: Record<string, unknown> = {};
const shape = (phases: any[]) =>
  phases.map((p) => ({
    id: p.id,
    name: p.name,
    duration: p.duration,
    gate: p.gate ? { name: p.gate.name, required: p.gate.requiredDeliverables ?? p.gate.deliverables ?? null } : null,
    tasks: (p.tasks ?? []).map((t: any) => ({
      id: t.id,
      name: t.name,
      owner: t.owner,
      days: t.durationDays ?? null,
      deps: t.dependsOn ?? [],
      evidence: t.evidence ?? null,
      isGate: !!t.isGate,
      deliverables: t.deliverables ?? null,
    })),
    phaseDeliverables: p.deliverables ?? null,
  }));

for (const tier of ["lite", "standard", "full"] as const) {
  out[`${tier}-none`] = shape(getNpdV3EffectivePhases({ tier, packs: [] }));
  out[`${tier}-all`] = shape(getNpdV3EffectivePhases({ tier, packs: ["battery", "cert", "software", "mold"] }));
}
out["packs"] = NPD_ADDON_PACKS.map((p) => ({ id: p.id, name: p.name, redline: !!p.redline, tasks: p.tasks.map((x) => ({ phase: x.phaseId, id: x.task.id, name: x.task.name, owner: x.task.owner, days: x.task.durationDays ?? null })) }));
out["legacy"] = shape(NPD_PHASES);
out["current"] = shape(NPD_PHASES_CURRENT);
writeFileSync(process.argv[2], JSON.stringify(out, null, 1));
console.log("ok", Object.keys(out).join(","));
