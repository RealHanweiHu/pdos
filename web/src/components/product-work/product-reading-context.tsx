"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { Observation } from "./competitors";
import type { Segment } from "./market-segments";
import type { OpportunityRecord } from "./opportunities";
import { ProductRequestError, request } from "./product-work-api";
import { useProductWorkUpdates } from "./product-work-scope";

type ScopedRecord = { id: string; product_line_id: string | null; state?: string; is_latest?: boolean; content?: { title?: string } };
export type ProductReading = {
  competitors?: Observation[];
  segments?: Segment[];
  opportunities?: OpportunityRecord[];
  experiments?: ScopedRecord[];
  definitions?: ScopedRecord[];
};
const ReadingContext = createContext<ProductReading>({});
export const useProductReading = () => useContext(ReadingContext);

/** Uses existing authorized domain reads; an unavailable collection remains unknown. */
export function ProductReadingProvider({ base, paused, onAuthorityLost, children }: { base: string; paused: boolean; onAuthorityLost: (message: string) => void; children: ReactNode }) {
  const [records, setRecords] = useState<ProductReading>({});
  const revision = useRef(0);
  const load = useCallback(async () => {
    const current = ++revision.current;
    const paths = { competitors: "competitors", segments: "market-segments", opportunities: "opportunities", experiments: "experiments", definitions: "definitions" } as const;
    const entries = await Promise.all(Object.entries(paths).map(async ([key, path]) => {
      try { const data = await request<{ items?: ScopedRecord[] }>(`${base}/${path}`); return [key, Array.isArray(data.items) ? data.items : undefined] as const; }
      catch (error) { if (error instanceof ProductRequestError && [401, 403].includes(error.status)) throw error; return [key, undefined] as const; }
    }));
    if (revision.current === current) setRecords(Object.fromEntries(entries) as ProductReading);
  }, [base]);
  const fail = useCallback((error: unknown) => { if (error instanceof ProductRequestError && [401, 403].includes(error.status)) { revision.current += 1; setRecords({}); onAuthorityLost(error.message); } }, [onAuthorityLost]);
  useEffect(() => { void load().catch(fail); return () => { revision.current += 1; }; }, [load, fail]);
  useProductWorkUpdates(base, load, { paused, onError: fail });
  return <ReadingContext.Provider value={records}>{children}</ReadingContext.Provider>;
}

export function inProductScope<T extends { product_line_id: string | null; is_latest?: boolean }>(records: T[] | undefined, scope: string) {
  return records?.filter(item => item.is_latest !== false && (scope === "all" || (item.product_line_id ?? "") === scope));
}
