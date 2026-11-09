"use client";

import type { DragEvent, ReactNode, RefObject } from "react";
import { ArrowUp, Square } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import styles from "./pai-conversation.module.css";

export function PaiComposer({
  value,
  onChange,
  onSubmit,
  onStop,
  disabled = false,
  busy = false,
  inputDisabled = false,
  sendDisabled = false,
  placeholder = "发消息给小Pai…",
  hint,
  tools,
  recovery,
  inputRef,
  background,
  attachments,
  onFileDrop,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop?: () => void;
  disabled?: boolean;
  busy?: boolean;
  inputDisabled?: boolean;
  sendDisabled?: boolean;
  placeholder?: string;
  hint?: string;
  tools?: ReactNode;
  recovery?: ReactNode;
  inputRef?: RefObject<HTMLTextAreaElement | null>;
  background?: ReactNode;
  /** Chips for what this turn carries, shown inside the box above the text (B14). */
  attachments?: ReactNode;
  /** F12: a file dropped on the box goes to the upload path; it is never sent directly. */
  onFileDrop?: (file: File) => void;
}) {
  const locked = disabled || busy;
  const files = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes("Files");
  const mark = (event: DragEvent<HTMLDivElement>, on: boolean) => { if (on) event.currentTarget.dataset.dragging = "true"; else delete event.currentTarget.dataset.dragging; };
  return <>
    {recovery}
    {background}
    <form onSubmit={event => { event.preventDefault(); if (!locked && !sendDisabled && value.trim()) onSubmit(); }}>
      <div className={styles.composerBox}
        onDragOver={onFileDrop && !locked ? event => { if (!files(event)) return; event.preventDefault(); mark(event, true); } : undefined}
        onDragLeave={onFileDrop ? event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) mark(event, false); } : undefined}
        onDrop={onFileDrop && !locked ? event => { if (!files(event)) return; event.preventDefault(); mark(event, false); const [file] = Array.from(event.dataTransfer.files); if (file) onFileDrop(file); } : undefined}>
        {onFileDrop && <div className={styles.dropHint} aria-hidden="true">松开即放到上传区，确认后随本条发送</div>}
        {attachments}
        <div className={styles.inputRow}>
          <textarea ref={inputRef} aria-label="发消息给小Pai" required minLength={1} maxLength={8000} rows={2}
            value={value} disabled={locked || inputDisabled} placeholder={placeholder}
            onChange={event => onChange(event.target.value)}
            onKeyDown={event => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                if (!locked && !sendDisabled && value.trim()) event.currentTarget.form?.requestSubmit();
              }
            }} />
          {onStop ? <Button type="button" className={`${styles.send} ${styles.stop}`} aria-label="停止回复" title="停止回复" disabled={disabled || busy} onClick={onStop}><Square size={12} weight="fill" aria-hidden="true"/></Button>
            : <Button className={styles.send} aria-label="发送消息" title="发送消息" disabled={locked || sendDisabled || !value.trim()}><ArrowUp size={17} aria-hidden="true"/></Button>}
        </div>
        {tools && <div className={styles.composerTools}>{tools}</div>}
      </div>
      <div className={styles.composerFooter}>{hint ?? "Enter 发送 · Shift Enter 换行"}</div>
    </form>
  </>;
}
