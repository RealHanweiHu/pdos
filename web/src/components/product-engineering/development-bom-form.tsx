import { type FormEvent, useRef, useState } from "react";

import { Button } from "@/components/ui/button";

import type {
  DevelopmentBomCreateInput,
  ProductSpecification,
} from "./product-engineering-types";

const controlClass =
  "mt-1 min-h-11 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:opacity-60";

export function DevelopmentBomForm({
  busy,
  onSubmit,
  specifications,
}: {
  busy: boolean;
  onSubmit: (input: DevelopmentBomCreateInput) => Promise<boolean>;
  specifications: ProductSpecification[];
}) {
  const formRef = useRef<HTMLFormElement>(null);
  const [specificationId, setSpecificationId] = useState(specifications[0]?.id ?? "");
  const effectiveSpecificationId = specifications.some((item) => item.id === specificationId)
    ? specificationId
    : (specifications[0]?.id ?? "");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const notes = String(data.get("notes") ?? "").trim();
    const saved = await onSubmit({
      specification_id: effectiveSpecificationId || null,
      bom_type: String(data.get("bom_type") ?? "ebom") as DevelopmentBomCreateInput["bom_type"],
      code: String(data.get("code") ?? "").trim(),
      name: String(data.get("name") ?? "").trim(),
      version: Number(data.get("version") ?? 1),
      notes: notes || null,
    });
    if (saved) formRef.current?.reset();
  }

  return (
    <form className="space-y-3 border-t p-4" onSubmit={submit} ref={formRef}>
      <h4 className="text-sm font-semibold">新建开发 BOM</h4>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium" htmlFor="development-bom-type">
          BOM 类型
          <select className={controlClass} disabled={busy} id="development-bom-type" name="bom_type">
            <option value="ebom">EBOM</option>
            <option value="prototype">Prototype BOM</option>
            <option value="cost">Cost BOM</option>
          </select>
        </label>
        <label className="text-xs font-medium" htmlFor="development-bom-specification">
          关联规格
          <select
            className={controlClass}
            disabled={busy || specifications.length === 0}
            id="development-bom-specification"
            onChange={(event) => setSpecificationId(event.target.value)}
            value={effectiveSpecificationId}
          >
            {specifications.length === 0 ? <option value="">暂无规格</option> : null}
            {specifications.map((item) => (
              <option key={item.id} value={item.id}>{item.code} · v{item.version}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="grid gap-3 sm:grid-cols-[1fr_96px]">
        <label className="text-xs font-medium" htmlFor="development-bom-code">
          BOM 编号
          <input className={controlClass} disabled={busy} id="development-bom-code" maxLength={64} name="code" required />
        </label>
        <label className="text-xs font-medium" htmlFor="development-bom-version">
          版本
          <input className={controlClass} defaultValue="1" disabled={busy} id="development-bom-version" min="1" name="version" required type="number" />
        </label>
      </div>
      <label className="block text-xs font-medium" htmlFor="development-bom-name">
        BOM 名称
        <input className={controlClass} disabled={busy} id="development-bom-name" maxLength={256} name="name" required />
      </label>
      <label className="block text-xs font-medium" htmlFor="development-bom-notes">
        备注（可选）
        <textarea className={`${controlClass} min-h-20 resize-y`} disabled={busy} id="development-bom-notes" maxLength={20_000} name="notes" />
      </label>
      <Button className="h-11 w-full sm:h-8 sm:w-auto" disabled={busy} type="submit">
        {busy ? "正在创建…" : "创建 BOM"}
      </Button>
    </form>
  );
}
