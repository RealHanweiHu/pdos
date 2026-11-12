"use client";
// D47 shared review card: shows the server's fixed preview before a T1 confirmation
// or a T2 named decision. The page submits the prepared command unchanged.
import type { ReactNode } from "react";
import { SealCheck, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { reviewEffect, tierNames, type PreparedCommand } from "@/lib/named-command";

type Props = { prepared: PreparedCommand; busy: boolean; onConfirm: () => void; onCancel: () => void; children?: ReactNode };

export function NamedCommandReview({ prepared, busy, onConfirm, onCancel, children }: Props) {
  const effect = reviewEffect(prepared.review);
  const named = prepared.tier === "T2";
  return <div role="group" aria-label={named ? "具名决定预览" : "确认预览"} className="space-y-2 rounded-lg border border-primary/40 bg-muted/30 p-3 text-sm">
    <p className="font-medium">{named ? "核对后由你本人具名办理" : "核对后确认一次"}<span className="subtle ml-2 text-xs">{tierNames[prepared.tier]}</span></p>
    {children}
    {effect && <p className="subtle text-xs [overflow-wrap:anywhere]">{effect}</p>}
    {prepared.expires_at && <p className="subtle text-xs">预览有效至 {new Date(prepared.expires_at).toLocaleTimeString("zh-CN", { hour12: false })}</p>}
    <div className="flex flex-wrap gap-2">
      <Button size="sm" disabled={busy} onClick={onConfirm}><SealCheck aria-hidden />{named ? "具名办理" : "确认"}</Button>
      <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel}><X aria-hidden />取消</Button>
    </div>
  </div>;
}
