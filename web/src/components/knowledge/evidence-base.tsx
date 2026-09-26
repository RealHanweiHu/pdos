"use client";

import { useEffect, useState } from "react";

import { WorkResponsibility } from "@/components/product-work/work-responsibility";
import { Button } from "@/components/ui/button";

type Source = {
  id: string;
  name: string;
  source_type: string;
  base_url: string | null;
  license_note: string | null;
  allowed_use: string;
  collection_frequency: string;
  retention_policy: string;
  trust_tier: string;
  status: string;
};

type Snapshot = {
  id: string;
  source_id: string | null;
  url: string | null;
  captured_at: string;
  content_digest: string;
  source_version: string | null;
  trust_tier: string;
  taint: string;
  superseded_by_id: string | null;
  conflicts_with_id: string | null;
  conflict_note: string | null;
  is_stale: boolean;
};

type LoadState = "loading" | "ready" | "error";

const TRUST_LABELS: Record<string, string> = {
  official: "官方",
  public: "公开",
  community: "社区",
  unknown: "未知",
};

// The taint label is the carrier for D25's 标注不拦截: external material is
// marked, never hidden, and the mark travels with every citation of it.
const TAINT_LABELS: Record<string, string> = {
  untrusted_external: "外部·未验证",
  internal: "内部",
  verified: "已验证",
};

const USE_LABELS: Record<string, string> = {
  internal_analysis: "仅内部分析",
  internal_citation: "可内部引用",
  redistribution: "可再分发",
};

export function EvidenceBase() {
  const [ownerLock, setOwnerLock] = useState<string | null>(null);
  const [sourceTarget, setSourceTarget] = useState("");
  const [sources, setSources] = useState<Source[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [state, setState] = useState<LoadState>("loading");
  const [error, setError] = useState<string | null>(null);
  const [staleOnly, setStaleOnly] = useState(false);
  const [content, setContent] = useState<{ snapshot_id: string; content: string; content_digest: string } | null>(null);
  const [contentError, setContentError] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const readContent = async (id: string) => {
    setReading(true); setContent(null); setContentError(null);
    try {
      const response = await fetch(`/api/evidence/snapshots/${id}/content`, { cache: "no-store" });
      const value = await response.json();
      if (!response.ok) throw new Error(value?.detail?.message ?? "正文暂不可用");
      setContent(value);
    } catch (failure) { setContentError(failure instanceof Error ? failure.message : "正文暂不可用"); }
    finally { setReading(false); }
  };

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [sourceResponse, snapshotResponse] = await Promise.all([
          fetch("/api/evidence/sources", { cache: "no-store" }),
          fetch("/api/evidence/snapshots", { cache: "no-store" }),
        ]);
        if (!sourceResponse.ok || !snapshotResponse.ok) {
          const failed = sourceResponse.ok ? snapshotResponse : sourceResponse;
          const body = await failed.json().catch(() => null);
          throw new Error(body?.detail?.message ?? "证据库暂不可用");
        }
        const sourceBody = await sourceResponse.json();
        const snapshotBody = await snapshotResponse.json();
        if (cancelled) return;
        setSources(sourceBody.items ?? []);
        const target = new URLSearchParams(window.location.search).get("source_owner_id");
        if (target && /^[0-9a-f-]{36}$/.test(target)) setSourceTarget(target);
        setSnapshots(snapshotBody.items ?? []);
        setState("ready");
      } catch (failure) {
        if (cancelled) return;
        setError(failure instanceof Error ? failure.message : "证据库暂不可用");
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (state === "ready" && sourceTarget) document.getElementById(`source-${sourceTarget}`)?.scrollIntoView({ block: "start" });
  }, [state, sourceTarget]);

  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">正在加载证据库…</p>;
  }
  if (state === "error") {
    return <p className="text-sm text-destructive">{error}</p>;
  }

  const sourceNames = new Map(sources.map((source) => [source.id, source.name]));
  const shown = staleOnly ? snapshots.filter((item) => item.is_stale) : snapshots;
  const staleCount = snapshots.filter((item) => item.is_stale).length;

  return (
    <div className="space-y-8" data-testid="evidence-base">
      {contentError && <p role="alert" className="text-sm text-destructive">{contentError}</p>}
      {content && <section className="space-y-2 rounded-lg border p-4"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">快照原始正文</h2><Button size="sm" variant="outline" onClick={() => setContent(null)}>关闭</Button></div><p className="break-all text-xs text-muted-foreground">{content.snapshot_id} · {content.content_digest}</p><pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{content.content}</pre></section>}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold">采集来源</h2>
        {sourceTarget && !sources.some(s => s.id === sourceTarget) && <p role="alert" className="text-sm text-destructive">指定来源不存在或不可访问。</p>}
        {sources.length === 0 ? (
          <p className="text-sm text-muted-foreground">尚未登记采集来源。</p>
        ) : (
          <ul className="space-y-2">
            {sources.map((source) => (
              <li id={`source-${source.id}`} key={source.id} className="rounded-md border p-3">
                <WorkResponsibility spaceId="" kind="source" recordId={source.id} initiallyOpen={sourceTarget === source.id} disabled={!!ownerLock && ownerLock !== source.id} onLock={value => setOwnerLock(value ? source.id : null)}/>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{source.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {source.source_type} · {TRUST_LABELS[source.trust_tier] ?? source.trust_tier}{" "}
                    · {USE_LABELS[source.allowed_use] ?? source.allowed_use} · 保留{" "}
                    {source.retention_policy} · {source.collection_frequency}
                  </span>
                </div>
                {source.base_url ? (
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {source.base_url}
                  </p>
                ) : null}
                {source.license_note ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    许可：{source.license_note}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold">证据快照</h2>
          <span className="text-xs text-muted-foreground">
            共 {snapshots.length} 份 · 已过期或被取代 {staleCount} 份
          </span>
          <Button
            className="ml-auto"
            variant="outline"
            size="sm"
            onClick={() => setStaleOnly((value) => !value)}
          >
            {staleOnly ? "显示全部" : "只看陈旧的"}
          </Button>
        </div>
        {shown.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {staleOnly ? "没有陈旧快照。" : "尚无证据快照。"}
          </p>
        ) : (
          <ul className="space-y-2">
            {shown.map((snapshot) => (
              <li key={snapshot.id} className="rounded-md border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded bg-muted px-1.5 py-0.5 text-xs">
                    {TAINT_LABELS[snapshot.taint] ?? snapshot.taint}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {TRUST_LABELS[snapshot.trust_tier] ?? snapshot.trust_tier} ·{" "}
                    {snapshot.source_id
                      ? (sourceNames.get(snapshot.source_id) ?? "未知来源")
                      : "人工上传"}
                    {snapshot.source_version ? ` · 版本 ${snapshot.source_version}` : ""}
                  </span>
                  {snapshot.is_stale ? (
                    <span className="text-xs text-destructive">陈旧</span>
                  ) : null}
                </div>
                <Button size="sm" variant="outline" disabled={reading} onClick={() => void readContent(snapshot.id)}>查看快照正文</Button>
                {snapshot.url ? (
                  <p className="mt-1 break-all font-mono text-xs text-muted-foreground">
                    {snapshot.url}
                  </p>
                ) : null}
                <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                  {snapshot.content_digest.slice(0, 16)}… ·{" "}
                  {new Date(snapshot.captured_at).toLocaleString()}
                </p>
                {snapshot.superseded_by_id ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    已被更新的快照取代（原快照保留，不可覆盖）
                  </p>
                ) : null}
                {snapshot.conflict_note ? (
                  <p className="mt-1 text-xs text-destructive">
                    冲突：{snapshot.conflict_note}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
