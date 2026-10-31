"use client";
import { useEffect, useRef, type ReactNode } from "react";
import { X } from "@phosphor-icons/react";
import s from "./platform.module.css";
import p from "./product-preview.module.css";
export function Sheet({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className={`${s.inspector} ${p.sheet}`}
      aria-label={title}
      onCancel={onClose}
    >
      <header>
        <span>{title}</span>
        <button aria-label={`关闭${title}`} onClick={onClose}>
          <X size={18} />
        </button>
      </header>
      <div className={s.inspectorBody}>{children}</div>
    </dialog>
  );
}
