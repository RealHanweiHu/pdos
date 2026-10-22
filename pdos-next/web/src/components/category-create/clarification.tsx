"use client";

import { Dialog } from "radix-ui";
import { Button } from "@/components/ui/button";

export type Question = {
  id: string; question: string; why: string; options: { value: string; label: string }[];
  recommended?: { value: string; reason: string } | null; depends_on?: string[]; allow_free_text: boolean;
};
type FormProps = {
  questions: Question[]; answers: Record<string, string>; disabled: boolean; prefix: string;
  onAnswer: (id: string, value: string) => void; onSubmit: () => void;
};

/** Visibility is checked when an unseen interrupt arrives, never on later focus. */
export function panelVisible(panel: HTMLElement | null): boolean {
  if (!panel || !panel.isConnected || panel.ownerDocument.visibilityState !== "visible") return false;
  const view = panel.ownerDocument.defaultView;
  if (!view || panel.closest("[hidden], [aria-hidden='true']")) return false;
  if (typeof panel.checkVisibility === "function" && !panel.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
  const rect = panel.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.right > 0
    && rect.top < view.innerHeight && rect.left < view.innerWidth;
}

export function ClarificationForm({ questions, answers, disabled, prefix, onAnswer, onSubmit }: FormProps) {
  const unanswered = questions.some(question => !answers[question.id]?.trim());
  return <form className="space-y-4" onSubmit={event => { event.preventDefault(); if (!disabled && !unanswered) onSubmit(); }}>
    {questions.map(question => <fieldset key={question.id} disabled={disabled} className="space-y-2 rounded-lg border p-3">
      <legend className="px-1 font-medium">{question.question}</legend>
      <p className="text-sm text-muted-foreground">{question.why}</p>
      {!!question.depends_on?.length && <p className="text-sm text-muted-foreground">依赖问题：{question.depends_on.map(id => questions.find(item => item.id === id)?.question ?? id).join("、")}</p>}
      {question.recommended && <div className="rounded-lg bg-muted p-3 text-sm">
        <p>建议：{question.options.find(option => option.value === question.recommended?.value)?.label ?? question.recommended.value}</p>
        <p className="mt-1 text-muted-foreground">推荐理由：{question.recommended.reason}</p>
        <p className="mt-1 text-muted-foreground">请你选择或填写答复。</p>
      </div>}
      {question.options.map(option => <label key={option.value} className="flex items-center gap-2 text-sm"><input type="radio" name={`${prefix}:${question.id}`}
        checked={answers[question.id] === option.value} onChange={() => onAnswer(question.id, option.value)} />{option.label}</label>)}
      {question.allow_free_text && <label className="block text-sm">补充答复<textarea value={answers[question.id] ?? ""} onChange={event => onAnswer(question.id, event.target.value)} /></label>}
    </fieldset>)}
    <Button disabled={disabled || unanswered}>提交答复并继续</Button>
  </form>;
}

export function ClarificationDialog({ open, onClose, onReturnFocus, ...form }: Omit<FormProps, "prefix"> & {
  open: boolean; onClose: () => void; onReturnFocus: () => void;
}) {
  return <Dialog.Root open={open} onOpenChange={value => { if (!value) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
      <Dialog.Content onCloseAutoFocus={event => { event.preventDefault(); onReturnFocus(); }}
        className="fixed left-1/2 top-1/2 z-50 max-h-[85vh] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border bg-background p-6 shadow-lg">
        <Dialog.Title className="text-lg font-semibold">小 Pai 需要你的答复</Dialog.Title>
        <Dialog.Description className="my-3 text-sm text-muted-foreground">核对以下问题后继续当前任务。关闭后仍可在对话中回答。</Dialog.Description>
        <ClarificationForm {...form} prefix="dialog" />
        <Button type="button" variant="ghost" className="mt-3" onClick={onClose}>稍后在对话中回答</Button>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
