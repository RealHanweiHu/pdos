"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { X } from "@phosphor-icons/react";
import styles from "./detail-sheet.module.css";

/** A scoped detail view. Native dialog supplies focus containment and Escape. */
export function DetailSheet({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    element?.showModal();
    return () => { element?.close(); if (trigger?.isConnected) trigger.focus(); };
  }, []);
  return <dialog ref={dialog} className={styles.sheet} aria-label={title} onCancel={event => { event.preventDefault(); onClose(); }}>
    <header><span>{title}</span><button type="button" aria-label={`关闭${title}`} onClick={onClose}><X size={18}/></button></header>
    <div className={styles.body}>{children}</div>
  </dialog>;
}
