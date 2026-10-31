"use client";

import { useCallback, useRef, useState } from "react";
import { createWorkProductFromRun, latestWorkProduct, originalWorkProduct, readWorkProducts, type WorkProduct, type WorkProductApi, type WorkProductRun } from "@/lib/work-products";

export function useWorkProducts(api: WorkProductApi, onUnavailable: () => void) {
  const generation = useRef(0);
  const writeLock = useRef(false);
  const pending = useRef<{ runId: string; kind: WorkProduct["kind"]; key: string } | null>(null);
  const [state, setState] = useState<{ sessionId: string; items: WorkProduct[]; openId: string | null; busy: boolean; error: string }>({ sessionId: "", items: [], openId: null, busy: false, error: "" });
  const clear = useCallback(() => { generation.current++; pending.current = null; setState({ sessionId: "", items: [], openId: null, busy: false, error: "" }); }, []);
  const load = useCallback(async (sessionId: string) => {
    const own = ++generation.current;
    setState(previous => ({ ...previous, sessionId, items: [], openId: null, busy: true, error: "" }));
    try {
      const items = await readWorkProducts(api, sessionId);
      if (own === generation.current) setState(previous => ({ ...previous, items, busy: false, error: "" }));
      return items;
    } catch (failure) {
      if (own === generation.current) {
        setState(previous => ({ ...previous, items: [], busy: false, error: failure instanceof Error ? failure.message : "成果暂不可读。" }));
        if ([401, 403].includes((failure as { status?: number }).status ?? 0)) { clear(); onUnavailable(); }
      }
      return null;
    }
  }, [api, clear, onUnavailable]);
  const open = useCallback((product: WorkProduct) => setState(previous => ({ ...previous, openId: product.id })), []);
  const openFromRun = useCallback(async (run: WorkProductRun, kind: WorkProduct["kind"]) => {
    if (writeLock.current) return null;
    writeLock.current = true;
    const own = ++generation.current;
    const request = pending.current?.runId === run.run_id && pending.current.kind === kind
      ? pending.current
      : { runId: run.run_id, kind, key: crypto.randomUUID() };
    pending.current = request;
    try {
      const existing = latestWorkProduct(state.items, run.run_id, kind);
      if (existing) { pending.current = null; open(existing); return existing; }
      setState(previous => ({ ...previous, busy: true, error: "" }));
      const product = await createWorkProductFromRun(api, run.run_id, kind, undefined, request.key);
      if (own !== generation.current) return null;
      pending.current = null;
      setState(previous => ({ ...previous, items: [...previous.items.filter(item => item.id !== product.id), product], openId: product.id, busy: false, error: "" }));
      return product;
    } catch (failure) {
      if (own !== generation.current) return null;
      const status = (failure as { status?: number }).status;
      if (status === 401 || status === 403) { clear(); onUnavailable(); }
      else if (status && status >= 400 && status < 500 && status !== 408 && status !== 429) pending.current = null;
      setState(previous => ({ ...previous, busy: false, error: failure instanceof Error ? failure.message : "成果暂不可创建。" }));
      return null;
    } finally {
      writeLock.current = false;
    }
  }, [api, clear, onUnavailable, open, state.items]);
  const close = useCallback(() => setState(previous => ({ ...previous, openId: null })), []);
  const reload = useCallback(async (current: WorkProduct) => {
    if (current.session_id !== state.sessionId) return null;
    const own = ++generation.current;
    setState(previous => ({ ...previous, busy: true, error: "" }));
    try {
      const items = await readWorkProducts(api, current.session_id);
      if (own !== generation.current) return null;
      const latest = items.filter(item => item.root_id === current.root_id).sort((a, b) => b.revision - a.revision)[0] ?? null;
      setState(previous => ({ ...previous, items, openId: latest?.id ?? previous.openId, busy: false, error: "" }));
      return latest;
    } catch (failure) {
      if (own !== generation.current) return null;
      if ([401, 403].includes((failure as { status?: number }).status ?? 0)) { clear(); onUnavailable(); }
      else setState(previous => ({ ...previous, busy: false, error: failure instanceof Error ? failure.message : "成果暂不可读。" }));
      return null;
    }
  }, [api, clear, onUnavailable, state.sessionId]);
  const saved = useCallback((product: WorkProduct) => {
    if (product.session_id !== state.sessionId) return;
    setState(previous => ({ ...previous, items: [...previous.items.filter(item => item.id !== product.id), product], openId: product.id }));
  }, [state.sessionId]);
  const openProduct = state.items.find(item => item.id === state.openId) ?? null;
  const original = openProduct ? originalWorkProduct(state.items, openProduct.root_id) : null;
  return { items: state.items, openProduct, original, open, openFromRun, close, reload, saved, load, clear, busy: state.busy, error: state.error };
}
