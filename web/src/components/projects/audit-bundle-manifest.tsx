import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";

const applicability: Record<string, string> = { applicable: "适用", not_applicable: "具名说明不适用", unconfirmed: "待确认" };
const kind: Record<string, string> = { gate: "Gate 签核与裁决", ecn: "ECN / ECR 签核", document: "项目文件原件" };

export function AuditBundleManifest({ manifest }: { manifest: Row }) {
  const documents = rows(manifest.documents), report = obj(manifest.report);
  return <section aria-label="附件包原文件与条款清单" className="space-y-3">
    <p className="break-words">报告：{text(report.filename)} · {text(report.template_version)}</p>
    <p className="text-xs break-all">包内位置：{text(report.path)} · 原报告校验：{text(report.sha256)}</p>
    {documents.length ? documents.map(file => <div key={text(file.id)} className="space-y-1 border-t pt-2">
      <p className="font-medium break-words">{text(file.filename)} · {Number(file.size_bytes).toLocaleString()} 字节</p>
      <p className="break-all text-xs">包内位置：{text(file.path)}</p>
      <p className="break-all text-xs">原件编号：{text(file.id)} · 校验：{text(file.sha256)}</p>
    </div>) : <p>未选择项目文件原件；包内仅含报告、清单与适用说明。</p>}
    {rows(manifest.clause_links).map((clause, index) => <section key={index} className="space-y-2 border-t pt-2">
      <h5 className="font-medium">条款 {index + 1} · {text(clause.standard)} / {text(clause.clause)}</h5>
      <p>版本：{text(clause.edition)} · {applicability[text(clause.applicability)] ?? text(clause.applicability)}</p>
      {rows(clause.references).length ? rows(clause.references).map((ref, at) => <div key={at} className="space-y-1 border-l pl-3">
        <p className="break-words">{kind[text(ref.kind)] ?? text(ref.kind)} · {text(documents.find(file => file.id === ref.id)?.filename) || text(ref.id)}</p>
        <p className="whitespace-pre-wrap">原件位置：{text(ref.position)}</p>
        <p className="whitespace-pre-wrap">条款对应：{text(ref.relevance)}</p>
        <p>登记有效截止日：{text(ref.valid_until) || "未登记，不推定有效"}</p>
      </div>) : <p>未选择原依据，待补项请查看原报告。</p>}
    </section>)}
    {Array.isArray(manifest.limitations) && <ul className="list-disc space-y-1 pl-5 text-muted-foreground">{manifest.limitations.map((limit, index) => <li key={index}>{text(limit)}</li>)}</ul>}
    <details><summary className="cursor-pointer">原始清单字段与编号</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(manifest, null, 2)}</pre></details>
  </section>;
}
