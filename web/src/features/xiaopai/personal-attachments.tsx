"use client";

import { useEffect, useRef, useState } from "react";
import { FileText, Image as ImageIcon, Paperclip, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { FileUpload, type DroppedFile, type UploadedSource } from "@/features/xiaopai/file-upload";
import { inputSourceReference, readPersonalSources, type PaiPersonalSource, type PaiPersonalSources, type PaiSourcesApi } from "@/lib/pai-sources";
import { isPhotoFilename } from "@/lib/pai-upload";
import styles from "./pai-conversation.module.css";
import picker from "./source-picker.module.css";

/** One registered source chosen for this personal turn; the server rebinds it on send (P91). */
export type CarriedSource = { artifact_id: string; expected_revision: number; title: string; category: string | null; filename: string | null };
type Category = { id: string; name: string };
const failureMessage = (failure: unknown) => failure instanceof Error ? failure.message : "资料暂不可读。";
const unavailable = (code: string | null) => ({
  SOURCE_STALE: "固定版本已变化，请刷新后重新选择。", SOURCE_UNAVAILABLE: "来源已撤回或不可继续使用。", FORBIDDEN_SCOPE: "当前不可使用该来源。",
  ORIGINAL_SECURITY_BLOCKED: "安全扫描或解析尚未完成。", ORIGINAL_SECURITY_UNAVAILABLE: "安全记录待核对。",
} as Record<string, string>)[code ?? ""] ?? "当前可用性待核对。";

export function carriedReferences(value: readonly CarriedSource[]) {
  return value.map(({ artifact_id, expected_revision }) => ({ artifact_id, expected_revision }));
}

export function CarriedChips({ value, onRemove, disabled }: { value: readonly CarriedSource[]; onRemove: (artifactId: string) => void; disabled?: boolean }) {
  if (!value.length) return null;
  return <div className={styles.carried} aria-label="本次携带的资料">
    {value.map(item => { const Icon = item.filename && isPhotoFilename(item.filename) ? ImageIcon : FileText; return <span key={item.artifact_id}>
      <Icon size={12} aria-hidden="true" />{item.title}{item.category && <em>· {item.category}</em>}
      <button type="button" disabled={disabled} aria-label={`移除附件 ${item.title}`} onClick={() => onRemove(item.artifact_id)}><X size={12} aria-hidden="true" /></button>
    </span>; })}
    <small>发送时按你当前的权限逐份核对；回答只给你本人看。</small>
  </div>;
}

type Props = {
  api: PaiSourcesApi; principalId: string; value: readonly CarriedSource[]; onChange: (value: CarriedSource[]) => void;
  open: boolean; onOpenChange: (open: boolean) => void; dropped: DroppedFile | null; disabled?: boolean;
};

/** Personal chat attachments: existing readable originals, or a new upload into one of your categories. */
export function PersonalAttachments({ api, principalId, value, onChange, open, onOpenChange, dropped, disabled }: Props) {
  const [categories, setCategories] = useState<Category[] | null>(null);
  const [target, setTarget] = useState("");
  const [reading, setReading] = useState<PaiPersonalSources | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const latest = useRef(value);
  useEffect(() => { latest.current = value; }, [value]);
  const add = (item: CarriedSource) => {
    const current = latest.current;
    if (current.some(row => row.artifact_id === item.artifact_id && row.expected_revision === item.expected_revision)) return;
    onChange([...current.filter(row => row.artifact_id !== item.artifact_id), item].slice(-8));
  };
  async function load(cursor?: string) {
    const own = ++generation.current;
    setLoading(true); setError("");
    try {
      const page = await readPersonalSources(api, principalId, { cursor });
      if (generation.current !== own) return;
      setReading(previous => cursor && previous ? { ...page, items: [...previous.items, ...page.items.filter(item => !previous.items.some(prior => prior.artifact_id === item.artifact_id))] } : page);
    } catch (failure) { if (generation.current === own) { setReading(null); setError(failureMessage(failure)); } }
    finally { if (generation.current === own) setLoading(false); }
  }
  useEffect(() => {
    if (!open) return;
    let active = true;
    void Promise.resolve().then(async () => {
      if (!active) return;
      if (!reading && !loading) await load();
      if (categories) return;
      try {
        const rows = await api<Category[]>("v1/categories");
        if (!active) return;
        const list = Array.isArray(rows) ? rows.filter(row => row && typeof row.id === "string" && typeof row.name === "string").map(row => ({ id: row.id, name: row.name })) : [];
        setCategories(list); setTarget(current => current || list[0]?.id || "");
      } catch (failure) { if (active) { setCategories([]); setError(failureMessage(failure)); } }
    });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- read once per opening; load() keeps its own generation.
  }, [open]);
  const category = categories?.find(row => row.id === target) ?? null;
  const choose = (source: PaiPersonalSource, checked: boolean) => {
    if (!source.availability.available) return;
    const { category, ...head } = source;
    const reference = inputSourceReference(head);
    if (checked) add({ ...reference, title: source.title, category: category.name, filename: source.original?.filename ?? null });
    else onChange(latest.current.filter(row => row.artifact_id !== source.artifact_id));
  };
  const uploaded = (source: UploadedSource) => {
    add({ artifact_id: source.artifact_id, expected_revision: source.expected_revision, title: source.title, category: category?.name ?? null, filename: source.filename || null });
    void load();
  };
  return <div className={picker.picker}>
    <Button type="button" variant="ghost" size="sm" className={picker.trigger} disabled={disabled} aria-expanded={open} aria-label="添加附件" title="添加附件" onClick={() => onOpenChange(!open)}>
      <Paperclip size={14} aria-hidden="true" />附件{value.length > 0 && <span>{value.length}</span>}
    </Button>
    {open && <section className={picker.panel} aria-label="添加附件">
      <div className={picker.heading}><strong>添加附件</strong><Button type="button" variant="ghost" size="sm" onClick={() => onOpenChange(false)}>收起</Button></div>
      <p className={picker.hint}>可选你有权读取的已登记原件，或上传新文件。原件仍归属所在品类，本次对话只携带你选的固定版本。</p>
      {categories && categories.length > 0 && <label className={picker.hint}>新文件存放到
        <select value={target} disabled={disabled} onChange={event => setTarget(event.target.value)} aria-label="新文件存放的品类">
          {categories.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
        </select>（仅本人可见）</label>}
      {categories && categories.length === 0 && <p className={picker.hint}>你还没有可存放原件的品类；仍可选择下面已登记的原件。</p>}
      {category && <FileUpload key={category.id} api={api} scope={{ principalId, categoryId: category.id, productId: null, proposalId: null }} dropped={dropped} onSourceReady={uploaded} disabled={disabled} />}
      <div className={picker.heading}><strong>选择已有原件</strong><Button type="button" variant="ghost" size="sm" disabled={disabled || loading} onClick={() => void load()}>刷新</Button></div>
      {loading && <p role="status">正在读取你可读的原件…</p>}{error && <p role="alert">{error}</p>}
      <div className={picker.list}>{reading?.items.map(source => <div className={picker.option} key={source.artifact_id}>
        <label className={picker.choice}><input type="checkbox" disabled={disabled || !source.availability.available}
          checked={value.some(row => row.artifact_id === source.artifact_id && row.expected_revision === source.artifact_revision)}
          onChange={event => choose(source, event.target.checked)} />
          <span><strong>{source.title}</strong><span className={picker.meta}>{source.category.name ?? "品类"} · v{source.artifact_revision}{source.original ? ` · ${source.original.filename}` : " · 登记资料"}</span></span></label>
        {!source.availability.available && <p className={picker.hint}>{unavailable(source.availability.code)}</p>}
      </div>)}</div>
      {reading && !reading.items.length && <p className={picker.hint}>暂无你可读的已登记原件。</p>}
      {reading?.next_cursor && <Button type="button" size="sm" variant="outline" disabled={disabled || loading} onClick={() => void load(reading.next_cursor!)}>加载更多</Button>}
    </section>}
  </div>;
}
