import { type FormEvent, useRef } from "react";

import { Button } from "@/components/ui/button";

import type { SpecificationCreateInput } from "./product-engineering-types";

const controlClass =
  "mt-1 min-h-11 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:opacity-60";

export function SpecificationForm({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (input: SpecificationCreateInput) => Promise<boolean>;
}) {
  const formRef = useRef<HTMLFormElement>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const saved = await onSubmit({
      code: String(data.get("code") ?? "").trim(),
      title: String(data.get("title") ?? "").trim(),
      version: Number(data.get("version") ?? 1),
      content: {},
    });
    if (saved) formRef.current?.reset();
  }

  return (
    <form className="space-y-3 border-t p-4" onSubmit={submit} ref={formRef}>
      <h4 className="text-sm font-semibold">新建规格版本</h4>
      <div className="grid gap-3 sm:grid-cols-[1fr_96px]">
        <label className="text-xs font-medium" htmlFor="specification-code">
          规格编号
          <input className={controlClass} disabled={busy} id="specification-code" maxLength={64} name="code" required />
        </label>
        <label className="text-xs font-medium" htmlFor="specification-version">
          版本
          <input className={controlClass} defaultValue="1" disabled={busy} id="specification-version" min="1" name="version" required type="number" />
        </label>
      </div>
      <label className="block text-xs font-medium" htmlFor="specification-title">
        规格标题
        <input className={controlClass} disabled={busy} id="specification-title" maxLength={512} name="title" required />
      </label>
      <Button className="h-11 w-full sm:h-8 sm:w-auto" disabled={busy} type="submit">
        {busy ? "正在创建…" : "创建规格"}
      </Button>
    </form>
  );
}
