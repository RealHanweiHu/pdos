"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Workspace } from "@/components/workspace";

type Category = { id: string; name: string; purpose: string };

async function categoryApi<T>(body?: unknown): Promise<T> {
  const response = await fetch("/api/v1/categories", {
    method: body === undefined ? "GET" : "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.message ?? "品类暂不可用。");
  return result;
}

export function CategoryWorkspace() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryId, setCategoryId] = useState("");
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [purpose, setPurpose] = useState("");
  useEffect(() => {
    let active = true;
    categoryApi<Category[]>().then(list => {
      if (!active) return;
      setCategories(list); setReady(true);
      const requested = new URLSearchParams(window.location.search).get("category");
      if (list.some(c => c.id === requested)) setCategoryId(requested!);
    }).catch(e => { if (active) { setError(e.message); setReady(true); } });
    return () => { active = false; };
  }, []);
  function selectCategory(id: string) {
    const url = new URL(window.location.href);
    url.searchParams.set("category", id); url.searchParams.delete("product");
    window.history.replaceState(null, "", url);
    setCategoryId(id);
  }
  if (categoryId) return <>
    <div className="flex items-center gap-3 border-b bg-background px-5 py-2">
      <span className="text-sm">品类 · {categories.find(c => c.id === categoryId)?.name}</span>
      <Button variant="ghost" size="sm" onClick={() => setCategoryId("")}>切换品类</Button>
    </div>
    <Workspace key={categoryId} categoryId={categoryId} />
  </>;
  return <main className="mx-auto max-w-3xl space-y-6 p-6">
    <h1 className="text-2xl font-semibold">品类工作区</h1>
    <p className="text-muted-foreground">选择品类，查看其中的型号与研发工作。</p>
    {error && <p role="alert">{error}</p>}
    {!ready && <p role="status">正在读取品类…</p>}
    <div className="grid gap-3 sm:grid-cols-2">{categories.map(c =>
      <button key={c.id} className="panel text-left" onClick={() => selectCategory(c.id)}>
        <strong>{c.name}</strong><p className="mt-2 text-sm text-muted-foreground">{c.purpose}</p>
      </button>)}</div>
    <form className="panel" onSubmit={async e => {
      e.preventDefault(); setBusy(true); setError("");
      try {
        const result = await categoryApi<{ subject_id: string }>({ name, purpose,
          idempotency_key: crypto.randomUUID(), confirmed: true });
        setCategories(await categoryApi<Category[]>()); selectCategory(result.subject_id);
      } catch (failure) { setError((failure as Error).message); }
      finally { setBusy(false); }
    }}>
      <h2 className="mb-4 font-semibold">建立品类</h2>
      <label>品类名称<input required minLength={2} maxLength={160} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>用途与范围<textarea required minLength={3} maxLength={1000} value={purpose} onChange={e => setPurpose(e.target.value)} /></label>
      <Button disabled={busy}>确认创建品类</Button>
    </form>
    {error && <Button variant="outline" disabled={busy} onClick={async () => {
      setBusy(true); setError("");
      try {
        const login = await fetch("/api/local-session", { method: "POST" });
        if (!login.ok) throw new Error("本地会话暂不可用。");
        setCategories(await categoryApi<Category[]>());
      } catch (failure) { setError((failure as Error).message); }
      finally { setBusy(false); }
    }}>进入本地合成环境</Button>}
  </main>;
}
