"use client";

import { isRecord } from "@/components/workspace-api";
export type WorkFocus = { kind: "task" | "issue" | "risk" | "capa" | "gate"; id: string };
export function parseWorkFocus(kind: string | null, id: string | null): WorkFocus | undefined {
  return id && kind && ["task", "issue", "risk", "capa", "gate"].includes(kind) && /^[0-9a-f-]{36}$/i.test(id) ? { kind: kind as WorkFocus["kind"], id } : undefined;
}
export function WorkFocusSummary({ value, historical = false }: { value: Record<string, unknown>; historical?: boolean }) {
  if (value.available === false) return <p className="text-sm text-destructive">原工作对象当前无权读取或已不可用；原内容与回答暂停展示。</p>;
  return <div className="space-y-2 rounded-md border p-3 text-sm">
    <p className="font-medium">{historical ? "本条固定对象" : "本次只使用所选对象资料"}：{String(value.title ?? "")}</p>
    {historical && value.current === false && <p className="text-destructive">原对象已变化，本条保留当时依据；继续提问须重新读取当前资料。</p>}
    <details><summary className="cursor-pointer text-primary">查看{historical ? "保存时" : "本次使用的"}字段</summary>
      {Array.isArray(value.fields) && value.fields.filter(isRecord).map((field, index) => <p key={index} className="mt-2 whitespace-pre-wrap break-words"><strong>{String(field.label)}：</strong>{String(field.value ?? "")}{field.truncated === true && <span className="text-pending">（长内容仅取片段，请打开原记录查看全文）</span>}</p>)}
    </details>
    <p className="text-xs text-muted-foreground">范围限上述字段；未读取关联文件全文，也不会直接修改或批准原业务。</p>
    {typeof value.href === "string" && value.href.startsWith("/projects?") && <a className="text-primary underline" href={value.href}>打开原对象办理</a>}
  </div>;
}
