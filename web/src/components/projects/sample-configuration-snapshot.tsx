"use client";

import { isRecord } from "@/components/workspace-api";

const fields: Record<string, string> = { pcb_version: "PCB", structure_version: "结构", fw_version: "固件", bom_code: "BOM", bom_version: "BOM版本", key_component_suppliers: "关键件供应商", build_date: "装机日期" };
function value(input: unknown) { return input === null || input === undefined || input === "" ? "未知" : typeof input === "object" ? JSON.stringify(input) : String(input); }
export function SampleConfigurationSnapshot({ revision, referenceOnly = false }: { revision: unknown; referenceOnly?: boolean }) {
  if (!isRecord(revision) || !isRecord(revision.snapshot)) return <p className="text-xs text-muted-foreground">当次配置未知。未用当前配置补写历史测试依据。</p>;
  const snapshot = revision.snapshot;
  return <div className="space-y-1 text-xs"><p className="font-medium">{referenceOnly ? "引用的样机配置" : "当次样机配置"} · 版本 {value(revision.revision_number)}</p><p className="text-muted-foreground">{referenceOnly ? "保存时的配置版本；与本次问题或验证的关系须另外核对" : revision.source === "report_extract" ? "来自本次报告，随测试结果一同核对" : "测试登记时绑定的配置；后续修改当前配置不改变本记录"}</p>
    <dl>{Object.entries(fields).map(([field, label]) => <div key={field}><dt className="inline">{label}：</dt><dd className="inline">{value(snapshot[field])}</dd></div>)}</dl>
  </div>;
}
