"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { X } from "@phosphor-icons/react";
import styles from "./detail-sheet.module.css";

type Size = "default" | "wide";

/** A scoped detail view. Native dialog supplies focus containment and Escape. */
export function DetailSheet({ title, onClose, children, size = "default" }: { title: string; onClose: () => void; children: ReactNode; size?: Size }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    element?.showModal();
    return () => { element?.close(); if (trigger?.isConnected) trigger.focus(); };
  }, []);
  return <dialog ref={dialog} className={styles.sheet} data-size={size} aria-label={title} onCancel={event => { if (event.target !== event.currentTarget) return; event.preventDefault(); onClose(); }}>
    <header><span>{title}</span><button type="button" aria-label={`关闭${title}`} onClick={onClose}><X size={18}/></button></header>
    <div className={size === "wide" ? styles.workBody : styles.body}>{children}</div>
  </dialog>;
}

/**
 * The same drawer for on-demand professional work, kept mounted while closed so
 * unsaved forms, pending requests and their recovery state survive reopening.
 */
export function RetainedSheet({ open, title, onClose, children, size = "wide" }: { open: boolean; title: string; onClose: () => void; children: ReactNode; size?: Size }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLElement | null>(null);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      trigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
      element.showModal();
    } else if (!open && element.open) {
      element.close();
      if (trigger.current?.isConnected) trigger.current.focus();
    }
  }, [open]);
  useEffect(() => { const element = dialog.current; return () => element?.close(); }, []);
  return <dialog ref={dialog} className={styles.sheet} data-size={size} aria-label={title} onCancel={event => { if (event.target !== event.currentTarget) return; event.preventDefault(); onClose(); }}>
    <header><span>{title}</span><button type="button" aria-label={`关闭${title}`} onClick={onClose}><X size={18}/></button></header>
    <div className={size === "wide" ? styles.workBody : styles.body}>{children}</div>
  </dialog>;
}
