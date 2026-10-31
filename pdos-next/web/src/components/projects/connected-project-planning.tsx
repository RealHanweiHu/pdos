"use client";

import { useEffect, useMemo, useState } from "react";
import { categoryTransport } from "@/lib/category-transport";
import type { ProjectApi } from "@/lib/project-plan-view";
import { Button } from "@/components/ui/button";
import { ProjectPlanning } from "./project-planning";

type Product = { id: string; name: string; purpose: string; revision: number };
export function ConnectedProjectPlanning({
  api,
  categoryId,
  productId,
  projectId,
  principalId,
  onSaved,
  compact = false,
}: {
  api: ProjectApi;
  categoryId: string;
  productId: string;
  projectId: string;
  principalId: string;
  compact?: boolean;
  onSaved: () => void | Promise<void>;
}) {
  const scoped = useMemo(
    () => categoryTransport(categoryId, api),
    [categoryId, api],
  );
  const [attempt, setAttempt] = useState(0);
  const key = `${principalId}:${categoryId}:${productId}:${projectId}:${attempt}`;
  const [reading, setReading] = useState<{
    key: string;
    api: ProjectApi;
    product: Product | null;
    error: string;
  } | null>(null);
  const current =
    reading?.key === key && reading.api === scoped ? reading : null;
  useEffect(() => {
    let active = true;
    void scoped<{ product: Product }>(`v1/products/${productId}/workspace`)
      .then((value) => {
        if (
          value.product.id !== productId ||
          !Number.isSafeInteger(value.product.revision) ||
          value.product.revision < 1
        )
          throw new Error("型号版本未完整取得。");
        if (active)
          setReading({ key, api: scoped, product: value.product, error: "" });
      })
      .catch((error) => {
        if (active)
          setReading({
            key,
            api: scoped,
            product: null,
            error: (error as Error).message,
          });
      });
    return () => {
      active = false;
    };
  }, [scoped, productId, key]);
  return !current ? (
    <p className="subtle" role="status">
      正在读取项目计划范围…
    </p>
  ) : current.error ? (
    <div role="alert">
      <p>{current.error}</p>
      <Button
        variant="outline"
        size="sm"
        onClick={() => setAttempt((value) => value + 1)}
      >
        重新读取计划范围
      </Button>
    </div>
  ) : (
    current.product && (
      <ProjectPlanning
        key={key}
        compact={compact}
        api={scoped}
        product={current.product}
        categoryId={categoryId}
        projectId={projectId}
        principalId={principalId}
        onSaved={onSaved}
      />
    )
  );
}
