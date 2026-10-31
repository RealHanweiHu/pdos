"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";

/** Opens the ordinary product shell; no case picker or alternate business UI. */
export function ProductPreviewEntry() {
  const started = useRef(false);
  const [error, setError] = useState("");
  const enter = useCallback(async () => {
    setError("");
    try {
      const result = await browserApi<{ href: string }>("preview-session", { mode: "workspace" });
      window.location.replace(result.href);
    } catch (failure) { setError((failure as Error).message); }
  }, []);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void enter();
  }, [enter]);
  return <main className="mx-auto max-w-lg px-6 py-16">
    <p className="font-semibold">PDOS</p>
    {error ? <div className="mt-6"><p role="alert">{error}</p><Button className="mt-4" onClick={() => void enter()}>重新进入工作台</Button></div>
      : <p role="status" className="mt-6 text-sm text-muted-foreground">正在打开你的研发工作台…</p>}
  </main>;
}
