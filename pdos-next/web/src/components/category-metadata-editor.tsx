"use client";

import { useEffect, useRef, useState } from "react";
import { PencilSimple } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import styles from "./category-home.module.css";

type Metadata = {
  id: string;
  name: string;
  purpose: string;
  revision: number;
  can_edit: boolean;
};
type Request = {
  name: string;
  purpose: string;
  expected_revision: number;
  idempotency_key: string;
};
export function CategoryMetadataEditor({
  categoryId,
  api,
  embedded = false,
  iconOnly = false,
}: {
  categoryId: string;
  api: typeof browserApi;
  embedded?: boolean;
  iconOnly?: boolean;
}) {
  const [data, setData] = useState<Metadata | null>(null);
  const [draft, setDraft] = useState<{ name: string; purpose: string } | null>(
    null,
  );
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const [pending, setPending] = useState<Request | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (open) dialog.current?.showModal();
    else dialog.current?.close();
  }, [open]);
  const lock = useRef(false),
    live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    void api<Metadata>(`v1/categories/${categoryId}/metadata`)
      .then((value) => {
        if (value.id !== categoryId) throw new Error("品类范围无法核对。");
        if (active) {
          setData(value);
          if (embedded)
            setDraft(
              (previous) =>
                previous ?? { name: value.name, purpose: value.purpose },
            );
          setError("");
        }
      })
      .catch((failure) => {
        if (active) {
          setData(null);
          setError(failure.message);
          if ([401, 403, 404].includes(failure.status)) {
            setDraft(null);
            setPending(null);
          }
        }
      });
    return () => {
      active = false;
    };
  }, [api, categoryId, reload, embedded]);
  async function save() {
    if (!data || !draft || lock.current) return;
    lock.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const request = pending ?? {
      ...draft,
      expected_revision: data.revision,
      idempotency_key: crypto.randomUUID(),
    };
    setPending(request);
    try {
      const result = await api<{
        id: string;
        subject_id: string;
        subject_revision: number;
      }>(`v1/categories/${categoryId}/metadata`, request);
      if (!live.current) return;
      if (!result.id || result.subject_id !== categoryId)
        throw new Error("保存回执暂不可核对，请重试原请求。");
      setData({
        ...data,
        name: request.name,
        purpose: request.purpose,
        revision: result.subject_revision,
      });
      setPending(null);
      setDraft(
        embedded ? { name: request.name, purpose: request.purpose } : null,
      );
      setOpen(false);
      setNotice("品类已更新");
      window.dispatchEvent(
        new CustomEvent("pdos:category-metadata-saved", {
          detail: { categoryId },
        }),
      );
    } catch (failure) {
      if (live.current) {
        const status = (failure as { status?: number }).status;
        setError(
          failure instanceof Error ? failure.message : "保存失败，请重试。",
        );
        if (
          status &&
          status >= 400 &&
          status < 500 &&
          ![408, 429].includes(status)
        )
          setPending(null);
        if ([401, 403, 404].includes(status ?? 0)) {
          setDraft(null);
          setData(null);
        }
      }
    } finally {
      lock.current = false;
      if (live.current) setBusy(false);
    }
  }
  const form = (
    <form
      className={styles.metadataEditor}
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      {error && <p role="alert">{error}</p>}
      {data && !data.can_edit && <p>当前没有修改品类的权限。</p>}
      {data && draft && data.can_edit && (
        <fieldset disabled={busy || !!pending}>
          <label>
            品类名称
            <input
              required
              maxLength={160}
              value={draft.name}
              onChange={(event) =>
                setDraft({ ...draft, name: event.target.value })
              }
            />
          </label>
          <label>
            主要场景
            <textarea
              required
              maxLength={4000}
              rows={3}
              value={draft.purpose}
              onChange={(event) =>
                setDraft({ ...draft, purpose: event.target.value })
              }
            />
          </label>
        </fieldset>
      )}
      <div className={styles.actions}>
        {data?.can_edit && (
          <Button
            size="sm"
            disabled={busy || !draft?.name.trim() || !draft?.purpose.trim()}
          >
            {busy ? "正在保存…" : pending ? "核对原保存请求" : "保存修改"}
          </Button>
        )}
        {error && !pending && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => setReload((value) => value + 1)}
          >
            读取最新版本
          </Button>
        )}
        {!embedded && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => setOpen(false)}
          >
            收起
          </Button>
        )}
      </div>
    </form>
  );
  if (embedded)
    return (
      <section aria-label="已保存品类编辑">
        {notice && <p role="status">{notice}</p>}
        {form}
      </section>
    );
  return (
    <div>
      <Button
        variant="ghost"
        size={iconOnly ? "icon" : "sm"}
        aria-label="编辑品类"
        title="编辑品类"
        disabled={!data && !error}
        onClick={() => {
          setOpen((value) => !value);
          if (data && !draft)
            setDraft({ name: data.name, purpose: data.purpose });
        }}
        aria-expanded={open}
      >
        <PencilSimple size={14} />
        {!iconOnly && "编辑品类"}
      </Button>
      {notice && (
        <span role="status" className="text-xs text-muted-foreground">
          {notice}
        </span>
      )}
      <dialog
        ref={dialog}
        className={styles.metadataDialog}
        aria-label="编辑品类"
        onCancel={() => setOpen(false)}
        onClose={() => setOpen(false)}
      >
        <h2>编辑品类</h2>
        {form}
      </dialog>
    </div>
  );
}
