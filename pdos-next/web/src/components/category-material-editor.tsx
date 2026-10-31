"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Plus, Sparkle, Trash } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { browserApi } from "@/lib/browser-api";
import {
  materialCommand,
  materialCandidateCommand,
  materialJournalKey,
  materialPages,
  materialWithdraw,
  restoreMaterialCommand,
  validMaterialPreview,
  validMaterialReceipt,
  type CategoryKnowledge,
  type CategoryParameter,
  type MaterialCommand,
  type MaterialKind,
  type MaterialPreview,
} from "@/lib/category-materials";
import styles from "./category-material-editor.module.css";
import type { DomainCommand } from "@/lib/domain-candidate";

export type MaterialContext = {
  request?: { id: string; prompt: string };
  kind: MaterialKind | "category" | "proposal" | "quality_issue" | "change_request";
  title: string;
  id?: string;
  version?: number;
  draft?: Record<string, unknown>;
};
type Item = CategoryKnowledge | CategoryParameter;
type Props = {
  onUnavailable?: () => void;
  candidate?: DomainCommand;
  categoryId: string;
  kind: MaterialKind;
  item: Item | null;
  parameters: CategoryParameter[];
  api: typeof browserApi;
  onClose: () => void;
  onSaved: (
    receipt?: import("@/lib/category-materials").MaterialReceipt,
  ) => void;
  onOpenPai: (context: MaterialContext) => void;
  onContextChange?: (context: MaterialContext | undefined) => void;
};
const labels = { competitor: "竞品", voice: "用户声音", parameter: "规格参数" };
const identity = (item: Item | null) =>
  item
    ? "parameter_id" in item
      ? item.parameter_id
      : item.lineage_id
    : undefined;
const initialFields = (
  kind: MaterialKind,
  item: Item | null,
): Record<string, unknown> =>
  item
    ? structuredClone(
        "parameter_id" in item
          ? { ...item, change_note: "" }
          : (item.content ?? {}),
      )
    : kind === "parameter"
      ? {
          key: "",
          name: "",
          value_type: "number",
          direction: "neutral",
          unit: "",
          standard_condition: "",
          method: "",
          acceptance_criterion: "",
          change_note: "",
          enum_values: [],
        }
      : kind === "voice"
        ? { label: "", source_platform: "", representative_refs: [] }
        : {
            brand: "",
            model: "",
            metrics: [],
            features: [],
            prices: [],
            segment_refs: [],
          };

export function CategoryMaterialEditor(props: Props) {
  const { api, categoryId, onUnavailable } = props;
  const [scope, setScope] = useState<{
      api: typeof browserApi;
      principal: string;
      revision: number;
    } | null>(null),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void Promise.all([
      api<{ principal_id: string }>("v1/session"),
      api<{ id: string; revision: number }[]>("v1/categories"),
    ])
      .then(([session, categories]) => {
        if (!active) return;
        const category = categories.find((row) => row.id === categoryId);
        if (!category) throw new Error("当前品类不可读，请重新选择。");
        setScope({
          api: api,
          principal: session.principal_id,
          revision: category.revision,
        });
      })
      .catch((failure) => {
        if (active) {
          setError(failure.message);
          if ([401, 403].includes(failure.status)) onUnavailable?.();
        }
      });
    return () => {
      active = false;
    };
  }, [api, categoryId, onUnavailable]);
  return scope?.api === props.api ? (
    <MaterialForm
      key={`${scope.principal}:${props.categoryId}:${props.kind}:${identity(props.item) ?? "new"}`}
      {...props}
      principal={scope.principal}
      categoryRevision={scope.revision}
    />
  ) : (
    <div className={styles.editor}>
      <Button size="sm" variant="ghost" onClick={props.onClose}>
        <ArrowLeft />
        返回资料
      </Button>
      <p role={error ? "alert" : "status"}>
        {error || "正在核对品类与本人身份…"}
      </p>
    </div>
  );
}

function MaterialForm({
  categoryId,
  kind,
  item,
  parameters,
  api,
  onClose,
  onSaved,
  onOpenPai,
  onContextChange,
  principal,
  categoryRevision,
  candidate,
  onUnavailable,
}: Props & { principal: string; categoryRevision: number }) {
  const [candidateSaved, setCandidateSaved] = useState(false);
  const activeCandidate = candidateSaved ? undefined : candidate;
  const [current, setCurrent] = useState<Item | null>(item),
    [fields, setFields] = useState(() =>
      candidate
        ? structuredClone(
            kind === "parameter"
              ? candidate.payload
              : (candidate.payload.content as Record<string, unknown>),
          )
        : initialFields(kind, item),
    );
  const [statement, setStatement] = useState(""),
    [reason, setReason] = useState("");
  const [prepared, setPrepared] = useState<MaterialPreview | null>(null),
    [pending, setPending] = useState<MaterialCommand | null>(null);
  const [ready, setReady] = useState(false),
    [busy, setBusy] = useState(false),
    [denied, setDenied] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [history, setHistory] = useState<Item[] | null>(null),
    [historyOpen, setHistoryOpen] = useState(false),
    [historyError, setHistoryError] = useState("");
  const live = useRef(false),
    lock = useRef(false),
    permissionEpoch = useRef(0);
  const target = identity(current) ?? `new:${kind}`,
    journal = materialJournalKey(
      principal,
      categoryId,
      `${target}${activeCandidate ? `:candidate:${activeCandidate.payload.candidate_digest}` : ""}`,
    );
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      try {
        const raw = sessionStorage.getItem(journal);
        setPending(
          raw
            ? restoreMaterialCommand(raw, categoryId, target, activeCandidate)
            : null,
        );
        setReady(true);
      } catch (failure) {
        setReady(false);
        setError((failure as Error).message);
      }
    });
    return () => {
      active = false;
    };
  }, [journal, target, categoryId, activeCandidate]);
  const readable =
    !current ||
    "parameter_id" in current ||
    (!!current.content && !current.source_changes?.length);
  const locked =
    !ready || busy || denied || !!pending || !!prepared || !readable;
  function change(key: string, value: unknown) {
    setFields((previous) => ({ ...previous, [key]: value }));
    setNotice("");
  }
  function fail(failure: unknown) {
    const value = failure as Error & { status?: number };
    setError(value.message);
    if (value.status === 401 || value.status === 403) {
      permissionEpoch.current++;
      setDenied(true);
      setCurrent(null);
      setFields({});
      setStatement("");
      setReason("");
      setHistory(null);
      setPrepared(null);
      setPending(null);
      onUnavailable?.();
      try {
        sessionStorage.removeItem(journal);
      } catch {
        /* The inaccessible material is hidden even if storage is unavailable. */
      }
    }
  }
  async function preview(withdraw = false) {
    if (lock.current || locked) return;
    lock.current = true;
    setBusy(true);
    setError("");
    const own = permissionEpoch.current;
    try {
      const command = withdraw
        ? materialWithdraw(categoryId, current as CategoryKnowledge, reason)
        : activeCandidate
          ? materialCandidateCommand(activeCandidate, kind, fields)
          : materialCommand(
              categoryId,
              categoryRevision,
              kind,
              fields,
              current,
              statement,
              principal,
            );
      const value = await api<unknown>(
        `v1/categories/${categoryId}/commands/preview`,
        command,
      );
      if (!live.current || own !== permissionEpoch.current) return;
      if (!validMaterialPreview(value, command))
        throw new Error("预览与本次资料不一致，未提交保存，请重新核对。");
      setPrepared(value);
    } catch (failure) {
      if (live.current) fail(failure);
    } finally {
      lock.current = false;
      if (live.current) setBusy(false);
    }
  }
  async function readSaved(id: string) {
    const list =
      kind === "parameter"
        ? await materialPages<CategoryParameter>(
            api,
            `v1/categories/${categoryId}/parameters?parameter_ids=${id}`,
          )
        : [
            ...(await materialPages<CategoryKnowledge>(
              api,
              `v1/categories/${categoryId}/knowledge?kind=${kind}&status=active`,
            )),
            ...(await materialPages<CategoryKnowledge>(
              api,
              `v1/categories/${categoryId}/knowledge?kind=${kind}&status=withdrawn`,
            )),
          ];
    const latest = list.find((row) => identity(row) === id);
    if (!latest)
      throw new Error("已保存，但最新版本暂不可读，请返回列表刷新。");
    return latest;
  }
  async function save(command: MaterialCommand) {
    if (lock.current || !ready || denied) return;
    if (
      !pending &&
      prepared?.expires_at &&
      Date.parse(prepared.expires_at) <= Date.now()
    ) {
      setPrepared(null);
      setError("预览已过期，请重新核对。");
      return;
    }
    lock.current = true;
    setBusy(true);
    setError("");
    let accepted = false;
    const own = permissionEpoch.current;
    try {
      const raw = JSON.stringify(command),
        existing = sessionStorage.getItem(journal);
      restoreMaterialCommand(raw, categoryId, target, activeCandidate);
      if (existing && existing !== raw)
        throw new Error("还有原保存请求待核对，未发送新请求。");
      sessionStorage.setItem(journal, raw);
      if (sessionStorage.getItem(journal) !== raw)
        throw new Error("原请求无法保存在本机，尚未发送。");
      setPending(command);
      setPrepared(null);
      const receipt = await api<unknown>(
        `v1/categories/${categoryId}/commands`,
        command,
      );
      if (!live.current || own !== permissionEpoch.current) return;
      if (!validMaterialReceipt(receipt, command))
        throw new Error("尚未取得一致的回执，请核对原保存请求。");
      accepted = true;
      setNotice(
        `已保存 · v${receipt.subject_revision}。可以继续编辑或与小Pai完善。`,
      );
      // The parent refreshes behind this workspace; the editor and chat stay mounted.
      onSaved(receipt);
      const latest = await readSaved(receipt.subject_id);
      if (!live.current || own !== permissionEpoch.current) return;
      sessionStorage.removeItem(journal);
      if (sessionStorage.getItem(journal) !== null)
        throw new Error("已保存，原请求记录尚未清理，请核对原请求。");
      setPending(null);
      setCurrent(latest);
      setCandidateSaved(true);
      setFields(initialFields(kind, latest));
      setStatement("");
      setReason("");
      setHistory(null);
    } catch (failure) {
      if (live.current) {
        fail(failure);
        const status = (failure as { status?: number }).status;
        if (
          !accepted &&
          status &&
          status >= 400 &&
          status < 500 &&
          ![408, 429].includes(status)
        ) {
          try {
            sessionStorage.removeItem(journal);
            setPending(null);
          } catch {
            setReady(false);
          }
          setNotice(
            "保存未完成，请核对错误后重新编辑；版本冲突时需返回列表读取新版。",
          );
        }
      }
    } finally {
      lock.current = false;
      if (live.current) setBusy(false);
    }
  }
  async function showHistory() {
    setHistoryOpen((value) => !value);
    if (history || !current || denied) return;
    const id = identity(current),
      own = permissionEpoch.current;
    setHistoryError("");
    try {
      const result =
        kind === "parameter"
          ? await materialPages<CategoryParameter>(
              api,
              `v1/categories/${categoryId}/parameters?parameter_ids=${id}&include_history=true`,
            )
          : [
              ...(await materialPages<CategoryKnowledge>(
                api,
                `v1/categories/${categoryId}/knowledge?kind=${kind}&include_history=true&status=active`,
              )),
              ...(await materialPages<CategoryKnowledge>(
                api,
                `v1/categories/${categoryId}/knowledge?kind=${kind}&include_history=true&status=withdrawn`,
              )),
            ];
      if (live.current && own === permissionEpoch.current)
        setHistory(
          result
            .filter((row) => identity(row) === id)
            .sort((a, b) => (b.version ?? 0) - (a.version ?? 0)),
        );
    } catch (failure) {
      if (live.current) {
        setHistoryError((failure as Error).message);
        fail(failure);
      }
    }
  }
  const text = (key: string) => String(fields[key] ?? "");
  const input = (key: string, label: string, wide = false) => (
    <label className={wide ? styles.wide : undefined}>
      {label}
      <input
        value={text(key)}
        onChange={(event) => change(key, event.target.value)}
        disabled={kind === "parameter" && !!current && key === "key"}
      />
    </label>
  );
  const list = (key: string) =>
    (fields[key] as Record<string, unknown>[]) ?? [];
  function updateRow(
    group: string,
    index: number,
    patch: Record<string, unknown>,
  ) {
    change(
      group,
      list(group).map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );
  }
  const title =
    kind === "parameter"
      ? text("name")
      : kind === "voice"
        ? text("label")
        : `${text("brand")} ${text("model")}`.trim();
  useEffect(() => {
    onContextChange?.(
      denied
        ? undefined
        : {
            kind,
            title: title || `新${labels[kind]}`,
            id:
              kind === "parameter"
                ? identity(current)
                : (current as CategoryKnowledge | null)?.id,
            version: current?.version,
            draft: {
              ...structuredClone(fields),
              unsaved_source_statement: statement,
              unsaved_withdraw_reason: reason,
            },
          },
    );
  }, [
    current,
    denied,
    fields,
    kind,
    onContextChange,
    title,
    statement,
    reason,
  ]);
  return (
    <section className={styles.editor} aria-label={`${labels[kind]}编辑区`}>
      <header className={styles.heading}>
        <Button variant="ghost" size="sm" onClick={onClose}>
          <ArrowLeft />
          返回资料
        </Button>
        <span>
          {activeCandidate
            ? "小Pai 起草 · 可直接编辑"
            : current
              ? `当前 v${current.version}`
              : `新增${labels[kind]}`}
        </span>
        <Button
          size="sm"
          variant="ghost"
          disabled={denied}
          onClick={() =>
            onOpenPai({
              kind,
              title: title || `新${labels[kind]}`,
              id:
                kind === "parameter"
                  ? identity(current)
                  : (current as CategoryKnowledge | null)?.id,
              version: current?.version,
              draft: {
                ...structuredClone(fields),
                unsaved_source_statement: statement,
                unsaved_withdraw_reason: reason,
              },
            })
          }
        >
          <Sparkle />
          小Pai 完善
        </Button>
      </header>
      <h2>{title || `新增${labels[kind]}`}</h2>
      {notice && (
        <p className={styles.notice} role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      {!readable && (
        <p role="alert">原资料或来源当前不可读，请返回列表刷新后重试。</p>
      )}
      {!denied && (
        <>
          <fieldset className={styles.fields} disabled={locked}>
            {kind === "parameter" ? (
              <>
                {input("name", "参数名称")}
                {input("key", "稳定参数键")}
                {input("unit", "单位")}
                <label>
                  数据类型
                  <select
                    value={text("value_type")}
                    onChange={(event) =>
                      change("value_type", event.target.value)
                    }
                  >
                    {Object.entries({
                      number: "数值",
                      range: "范围",
                      text: "文本",
                      boolean: "是 / 否",
                      enum: "枚举",
                    }).map(([key, label]) => (
                      <option key={key} value={key}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  优化方向
                  <select
                    value={text("direction")}
                    onChange={(event) =>
                      change("direction", event.target.value)
                    }
                  >
                    <option value="neutral">无偏好</option>
                    <option value="higher">越高越好</option>
                    <option value="lower">越低越好</option>
                    <option value="target">目标值</option>
                  </select>
                </label>
                {fields.value_type === "enum" && (
                  <label>
                    枚举值（逗号分隔）
                    <input
                      value={((fields.enum_values as string[]) ?? []).join(
                        "，",
                      )}
                      onChange={(event) =>
                        change("enum_values", event.target.value.split(/[,，]/))
                      }
                    />
                  </label>
                )}
                {input("standard_condition", "标准工况", true)}
                {input("method", "验证方法", true)}
                {input("acceptance_criterion", "通过判据", true)}
                {input("change_note", "本次修订说明", true)}
              </>
            ) : kind === "voice" ? (
              <>
                <label className={styles.wide}>
                  用户声音
                  <textarea
                    rows={3}
                    value={text("label")}
                    onChange={(event) => change("label", event.target.value)}
                  />
                </label>
                {input("source_platform", "来源平台", true)}
              </>
            ) : (
              <>
                {input("brand", "品牌")}
                {input("model", "型号")}
              </>
            )}
            {kind === "competitor" && (
              <>
                <div className={styles.wide}>
                  <div className={styles.sectionHead}>
                    <h3>价格记录</h3>
                    <Button
                      size="xs"
                      variant="ghost"
                      onClick={() =>
                        change("prices", [
                          ...list("prices"),
                          {
                            amount: null,
                            currency: null,
                            observed_on: null,
                            price_type: "unknown",
                            includes_tax: null,
                            includes_shipping: null,
                            channel: null,
                            region: null,
                            source_ref: null,
                          },
                        ])
                      }
                    >
                      <Plus />
                      新增价格
                    </Button>
                  </div>
                  <div className={styles.scroll}>
                    <table>
                      <thead>
                        <tr>
                          <th>金额 / 币种</th>
                          <th>日期 / 类型</th>
                          <th>税运口径</th>
                          <th>渠道 / 地区</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {list("prices").map((row, index) => (
                          <tr key={index}>
                            <td>
                              {["amount", "currency"].map((key) => (
                                <input
                                  key={key}
                                  aria-label={`价格 ${index + 1} ${key === "amount" ? "金额" : "币种"}`}
                                  placeholder={
                                    key === "amount" ? "未知" : "币种"
                                  }
                                  value={String(row[key] ?? "")}
                                  onChange={(event) =>
                                    updateRow("prices", index, {
                                      [key]: event.target.value || null,
                                    })
                                  }
                                />
                              ))}
                            </td>
                            <td>
                              <input
                                aria-label={`价格 ${index + 1} 日期`}
                                type="date"
                                value={String(row.observed_on ?? "")}
                                onChange={(event) =>
                                  updateRow("prices", index, {
                                    observed_on: event.target.value || null,
                                  })
                                }
                              />
                              <select
                                aria-label={`价格 ${index + 1} 类型`}
                                value={String(row.price_type)}
                                onChange={(event) =>
                                  updateRow("prices", index, {
                                    price_type: event.target.value,
                                  })
                                }
                              >
                                <option value="unknown">类型未知</option>
                                <option value="retail">零售</option>
                                <option value="promo">促销</option>
                              </select>
                            </td>
                            <td>
                              {["includes_tax", "includes_shipping"].map(
                                (key) => (
                                  <select
                                    key={key}
                                    aria-label={`价格 ${index + 1} ${key === "includes_tax" ? "含税" : "含运"}`}
                                    value={
                                      row[key] === null
                                        ? "unknown"
                                        : String(row[key])
                                    }
                                    onChange={(event) =>
                                      updateRow("prices", index, {
                                        [key]:
                                          event.target.value === "unknown"
                                            ? null
                                            : event.target.value === "true",
                                      })
                                    }
                                  >
                                    <option value="unknown">
                                      {key === "includes_tax" ? "税" : "运"}未知
                                    </option>
                                    <option value="true">
                                      含{key === "includes_tax" ? "税" : "运"}
                                    </option>
                                    <option value="false">
                                      未含{key === "includes_tax" ? "税" : "运"}
                                    </option>
                                  </select>
                                ),
                              )}
                            </td>
                            <td>
                              {["channel", "region"].map((key) => (
                                <input
                                  key={key}
                                  aria-label={`价格 ${index + 1} ${key === "channel" ? "渠道" : "地区"}`}
                                  value={String(row[key] ?? "")}
                                  placeholder={
                                    key === "channel" ? "渠道" : "地区"
                                  }
                                  onChange={(event) =>
                                    updateRow("prices", index, {
                                      [key]: event.target.value || null,
                                    })
                                  }
                                />
                              ))}
                            </td>
                            <td>
                              <Button
                                size="icon-xs"
                                variant="ghost"
                                aria-label={`删除价格 ${index + 1}`}
                                onClick={() =>
                                  change(
                                    "prices",
                                    list("prices").filter(
                                      (_, i) => i !== index,
                                    ),
                                  )
                                }
                              >
                                <Trash />
                              </Button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {!list("prices").length && (
                    <p className={styles.muted}>
                      暂无价格；币种、日期与税运口径分别保留。
                    </p>
                  )}
                </div>
                <div className={styles.wide}>
                  <div className={styles.sectionHead}>
                    <h3>规格与特性</h3>
                    <select
                      aria-label="从品类字典添加竞品参数"
                      value=""
                      onChange={(event) => {
                        const parameter = parameters.find(
                          (row) => row.parameter_id === event.target.value,
                        );
                        if (parameter)
                          change("metrics", [
                            ...list("metrics"),
                            {
                              parameter_id: parameter.parameter_id,
                              parameter_version: parameter.version,
                              value: null,
                              lower: null,
                              upper: null,
                              text: null,
                              unit: parameter.unit,
                              condition_note:
                                parameter.standard_condition ?? null,
                              nature: "unknown",
                              source_ref: null,
                            },
                          ]);
                      }}
                    >
                      <option value="">添加参数…</option>
                      {parameters
                        .filter(
                          (parameter) =>
                            ![...list("metrics"), ...list("features")].some(
                              (row) =>
                                row.parameter_id === parameter.parameter_id &&
                                row.parameter_version === parameter.version,
                            ),
                        )
                        .map((parameter) => (
                          <option
                            key={parameter.parameter_id}
                            value={parameter.parameter_id}
                          >
                            {parameter.name} · v{parameter.version}
                          </option>
                        ))}
                    </select>
                  </div>
                  <div className={styles.scroll}>
                    <table>
                      <thead>
                        <tr>
                          <th>参数 / 固定版本</th>
                          <th>数值或文本</th>
                          <th>上下限</th>
                          <th>性质 / 工况</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {["metrics", "features"].flatMap((group) =>
                          list(group).map((row, index) => (
                            <tr key={`${group}:${index}`}>
                              <td>
                                {parameters.find(
                                  (parameter) =>
                                    parameter.parameter_id ===
                                      row.parameter_id &&
                                    parameter.version === row.parameter_version,
                                )?.name ?? "历史参数"}
                                <small>
                                  v{String(row.parameter_version)} ·{" "}
                                  {String(row.unit ?? "无单位")}
                                </small>
                              </td>
                              <td>
                                <input
                                  aria-label={`${group} ${index + 1} 数值`}
                                  placeholder="数值未知"
                                  value={String(row.value ?? "")}
                                  onChange={(event) =>
                                    updateRow(group, index, {
                                      value: event.target.value || null,
                                    })
                                  }
                                />
                                <input
                                  aria-label={`${group} ${index + 1} 文本`}
                                  placeholder="文本"
                                  value={String(row.text ?? "")}
                                  onChange={(event) =>
                                    updateRow(group, index, {
                                      text: event.target.value || null,
                                    })
                                  }
                                />
                              </td>
                              <td>
                                {["lower", "upper"].map((key) => (
                                  <input
                                    key={key}
                                    aria-label={`${group} ${index + 1} ${key === "lower" ? "下限" : "上限"}`}
                                    placeholder={
                                      key === "lower" ? "下限未知" : "上限未知"
                                    }
                                    value={String(row[key] ?? "")}
                                    onChange={(event) =>
                                      updateRow(group, index, {
                                        [key]: event.target.value || null,
                                      })
                                    }
                                  />
                                ))}
                              </td>
                              <td>
                                <select
                                  aria-label={`${group} ${index + 1} 性质`}
                                  value={String(row.nature)}
                                  onChange={(event) =>
                                    updateRow(group, index, {
                                      nature: event.target.value,
                                    })
                                  }
                                >
                                  <option value="unknown">未知</option>
                                  <option value="measured">实测</option>
                                  <option value="claimed">宣传</option>
                                  <option value="inferred">推断</option>
                                </select>
                                <input
                                  aria-label={`${group} ${index + 1} 工况`}
                                  placeholder="工况未知"
                                  value={String(row.condition_note ?? "")}
                                  onChange={(event) =>
                                    updateRow(group, index, {
                                      condition_note:
                                        event.target.value || null,
                                    })
                                  }
                                />
                              </td>
                              <td>
                                <Button
                                  size="icon-xs"
                                  variant="ghost"
                                  aria-label={`删除 ${group} 参数 ${index + 1}`}
                                  onClick={() =>
                                    change(
                                      group,
                                      list(group).filter((_, i) => i !== index),
                                    )
                                  }
                                >
                                  <Trash />
                                </Button>
                              </td>
                            </tr>
                          )),
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            )}
            {kind !== "parameter" && !activeCandidate && (
              <label className={styles.wide}>
                补充本人来源说明
                <textarea
                  rows={2}
                  placeholder="填写后会作为具名陈述保存；原有固定来源仍然保留。"
                  value={statement}
                  onChange={(event) => setStatement(event.target.value)}
                />
              </label>
            )}
          </fieldset>
          {activeCandidate && (
            <details className={styles.history}>
              <summary>原稿与来源</summary>
              <p className={styles.muted}>
                小Pai 原稿保留；你的修改会随本次保存记录。
              </p>
              {(
                (activeCandidate.payload.source_refs as
                  | import("@/lib/category-materials").MaterialRef[]
                  | undefined) ?? []
              ).map((ref, index) => (
                <p key={index} className={styles.muted}>
                  {ref.statement ||
                    ref.quote ||
                    `${ref.type} · v${ref.version}`}
                </p>
              ))}
            </details>
          )}
          {current && (
            <div className={styles.history}>
              <Button
                size="xs"
                variant="ghost"
                onClick={() => void showHistory()}
              >
                {historyOpen ? "收起版本历史" : "查看版本历史"}
              </Button>
              {historyOpen && (
                <div>
                  {historyError ? (
                    <p role="alert">{historyError}</p>
                  ) : !history ? (
                    <p role="status">正在读取历史…</p>
                  ) : (
                    history.map((row) => (
                      <details key={row.version}>
                        <summary>
                          v{row.version} ·{" "}
                          {"parameter_id" in row
                            ? row.change_note || row.name
                            : `${row.status === "withdrawn" ? "撤回" : "资料版本"} · ${row.origin === "human" ? "人工" : row.origin === "ai_draft" ? "AI 草稿" : "导入"}`}
                        </summary>
                        <pre>
                          {JSON.stringify(
                            "parameter_id" in row ? row : row.content,
                            null,
                            2,
                          )}
                        </pre>
                      </details>
                    ))
                  )}
                </div>
              )}
            </div>
          )}
          {kind !== "parameter" &&
            !activeCandidate &&
            current &&
            "status" in current &&
            current.status !== "withdrawn" && (
              <details className={styles.history}>
                <summary>撤回资料</summary>
                <label>
                  撤回理由
                  <input
                    value={reason}
                    disabled={locked}
                    onChange={(event) => setReason(event.target.value)}
                  />
                </label>
                <Button
                  variant="outline"
                  size="xs"
                  disabled={locked || !reason.trim()}
                  onClick={() => void preview(true)}
                >
                  核对撤回
                </Button>
              </details>
            )}
          <footer className={styles.footer}>
            {pending ? (
              <>
                <span>保存结果待核对，原请求已保留。</span>
                <Button
                  size="sm"
                  disabled={busy || !ready}
                  onClick={() => void save(pending)}
                >
                  核对原保存请求
                </Button>
              </>
            ) : prepared ? (
              <>
                <span>
                  {prepared.command.operation === "category.knowledge.withdraw"
                    ? "确认撤回此资料，历史仍保留。"
                    : "确认保存当前内容，追加一个版本。"}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => setPrepared(null)}
                >
                  返回编辑
                </Button>
                <Button
                  size="sm"
                  disabled={busy}
                  onClick={() => void save(prepared.command)}
                >
                  确认保存
                </Button>
              </>
            ) : (
              <>
                <span>
                  {kind === "parameter"
                    ? "旧提案继续引用原参数版本。"
                    : current &&
                        "status" in current &&
                        current.status === "withdrawn"
                      ? "保存将追加新版本并恢复此资料。"
                      : "资料在当前品类共享。"}
                </span>
                <Button
                  size="sm"
                  disabled={locked}
                  onClick={() => void preview()}
                >
                  核对并保存
                </Button>
              </>
            )}
          </footer>
        </>
      )}
    </section>
  );
}
