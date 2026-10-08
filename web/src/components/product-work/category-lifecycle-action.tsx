"use client";

import { ArrowCounterClockwiseIcon, TrashIcon } from "@phosphor-icons/react";
import { Dialog } from "radix-ui";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { command, ProductRequestError, request, type Space } from "./product-work-api";

export function CategoryLifecycleAction({ space, disabled, compact = false, onChanged, onPendingChange }: {
  space: Space;
  disabled: boolean;
  compact?: boolean;
  onChanged: (space: Space) => void;
  onPendingChange: (pending: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const attempt = useRef<ReturnType<typeof command> & { lifecycle: string; reason: string } | null>(null);
  const archived = space.lifecycle === "archived";
  const label = archived ? "恢复品类" : "删除品类";
  const Icon = archived ? ArrowCounterClockwiseIcon : TrashIcon;

  async function confirm() {
    if (saving || disabled) return;
    setSaving(true); setError(""); onPendingChange(true);
    attempt.current ??= { ...command(space), lifecycle: archived ? "active" : "archived", reason: archived ? "人工确认恢复品类" : "人工确认删除品类，归档保留资料与历史" };
    try {
      const saved = await request<Space>(`spaces/${space.id}/lifecycle`, "POST", attempt.current);
      attempt.current = null;
      setOpen(false);
      onChanged(saved);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "操作结果暂未确认，请重试原请求");
      // Keep the original command after a transport failure, including across reopening.
      if (failure instanceof ProductRequestError && [400, 401, 403, 404, 409, 422].includes(failure.status)) attempt.current = null;
    } finally {
      setSaving(false); onPendingChange(false);
    }
  }

  return <Dialog.Root open={open} onOpenChange={value => { if (!saving) { setOpen(value); if (value) setError(""); } }}>
    <Dialog.Trigger asChild>
      <Button type="button" variant="ghost" size="sm" className={archived ? "min-h-11 justify-start sm:min-h-8" : "min-h-11 justify-start text-destructive hover:text-destructive sm:min-h-8"} disabled={disabled} aria-label={`${label} ${space.title}`}>
        <Icon aria-hidden="true" className="size-4" />{compact ? archived ? "恢复" : "删除" : label}
      </Button>
    </Dialog.Trigger>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
      <Dialog.Content className="fixed left-1/2 top-1/2 z-[60] w-[calc(100%_-_2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border bg-background p-5 shadow-xl">
        <Dialog.Title className="text-lg font-semibold">{label}“{space.title}”？</Dialog.Title>
        <Dialog.Description className="mt-3 text-sm leading-6 text-muted-foreground">
          {archived ? "恢复后将重新显示在品类列表，保留原资料、成员权限和版本历史。" : "删除后移入“已归档”，从默认品类列表移除。资料、提案及版本历史会保留，可在已归档列表恢复。未结束的工作和待审核事项须先处置。"}
        </Dialog.Description>
        {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <Dialog.Close asChild><Button type="button" variant="outline" disabled={saving}>取消</Button></Dialog.Close>
          <Button type="button" variant={archived ? "default" : "destructive"} disabled={saving || disabled} onClick={() => void confirm()}>{saving ? "正在处理…" : error ? "重试" : archived ? "确认恢复" : "确认删除"}</Button>
        </div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
