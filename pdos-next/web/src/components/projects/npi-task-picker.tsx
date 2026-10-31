"use client";
import { useEffect, useRef, useState } from "react";
import { X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type {
  NpiTemplate,
  ProjectWorkApi,
  WorkScope,
  WorkOutcome,
} from "@/lib/project-work";
import styles from "./project-work.module.css";
export type NpiTask = {
  reference: NpiTemplate;
  title: string;
  goal: string;
  deliverables: string[];
  checks: WorkOutcome[];
};
export function NpiTaskPicker({
  api,
  scope,
  onChoose,
  disabled,
}: {
  api: ProjectWorkApi;
  scope: WorkScope;
  onChoose: (task: NpiTask) => void;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false),
    [data, setData] = useState<NpiTask[] | null>(null),
    [error, setError] = useState(""),
    [query, setQuery] = useState(""),
    [projectType, setProjectType] = useState("npd"),
    [phase, setPhase] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const { categoryId, productId, projectId } = scope;
  useEffect(() => {
    if (open) dialog.current?.showModal();
    else dialog.current?.close();
  }, [open]);
  useEffect(() => {
    let active = true;
    if (open)
      void api<{ items: NpiTask[] }>(
        `v1/categories/${categoryId}/products/${productId}/project-work/templates?project_id=${projectId}`,
      )
        .then((value) => {
          if (active) {
            setData(value.items);
            setError("");
          }
        })
        .catch((failure) => {
          if (active) {
            setData(null);
            setError(failure.message);
          }
        });
    return () => {
      active = false;
    };
  }, [api, categoryId, productId, projectId, open]);
  const items = (data ?? []).filter(
    (row) =>
      (!projectType || row.reference.project_type === projectType) &&
      (!phase || row.reference.phase_id === phase) &&
      `${row.title} ${row.deliverables.join(" ")}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
  );
  const phases = [
    ...new Map(
      (data ?? [])
        .filter(
          (row) => !projectType || row.reference.project_type === projectType,
        )
        .map((row) => [row.reference.phase_id, row.reference]),
    ).values(),
  ];
  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        从 NPI 模板添加
      </Button>
      <dialog
        className={styles.templateDialog}
        ref={dialog}
        onCancel={() => setOpen(false)}
      >
        <header className={styles.heading}>
          <h3>选择 NPI 任务</h3>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="关闭 NPI 任务选择"
            onClick={() => setOpen(false)}
          >
            <X />
          </Button>
        </header>
        <div className={styles.toolbar}>
          <input
            aria-label="搜索 NPI 模板任务"
            type="search"
            placeholder="任务或交付物"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <select
            aria-label="模板项目类型"
            value={projectType}
            onChange={(event) => {
              setProjectType(event.target.value);
              setPhase("");
            }}
          >
            <option value="">所有类型</option>
            {[
              ...new Set((data ?? []).map((row) => row.reference.project_type)),
            ].map((type) => (
              <option key={type} value={type}>
                {{
                  npd: "新产品开发",
                  derivative: "衍生开发 · DRV",
                  eco: "工程变更 · ECO",
                  idr: "IDR",
                  jdm: "联合开发 · JDM",
                  obt: "OBT",
                }[type] ?? type.toUpperCase()}
              </option>
            ))}
          </select>
          <select
            aria-label="模板阶段"
            value={phase}
            onChange={(event) => setPhase(event.target.value)}
          >
            <option value="">所有阶段</option>
            {phases.map((row) => (
              <option key={row.phase_id} value={row.phase_id}>
                {row.phase_name}
              </option>
            ))}
          </select>
        </div>
        {error ? (
          <p role="alert">{error}</p>
        ) : !data ? (
          <p>正在读取模板…</p>
        ) : (
          <div className={styles.templateList}>
            {items.map((row) => (
              <button
                type="button"
                key={`${row.reference.project_type}:${row.reference.phase_id}:${row.reference.task_id}`}
                onClick={() => {
                  onChoose(row);
                  setOpen(false);
                }}
              >
                <span>
                  <strong>{row.title}</strong>
                  <small>{row.deliverables.join(" · ")}</small>
                </span>
                <span>{row.reference.phase_name}</span>
              </button>
            ))}
            {!items.length && <p>没有符合条件的任务</p>}
          </div>
        )}
        <p className={styles.note}>
          选择后可完善交付成果和项目依据，再保存为项目任务。
        </p>
      </dialog>
    </>
  );
}
