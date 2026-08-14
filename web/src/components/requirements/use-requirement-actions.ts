"use client";

import { useState } from "react";

import { isRecord, responseBody } from "@/components/workspace-api";

import { readRequirement } from "./requirement-api";
import type { RequirementConversionValues } from "./requirement-conversion-form";
import type { RequirementFormValues } from "./requirement-form";
import type { Requirement } from "./requirement-types";

export function useRequirementActions({
  push,
  replace,
}: {
  push: (href: string) => void;
  replace: (href: string) => void;
}) {
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [convertingId, setConvertingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const editingRequirement =
    requirements.find((requirement) => requirement.id === editingId) ?? null;
  const convertingRequirement =
    requirements.find((requirement) => requirement.id === convertingId) ?? null;

  async function createRequirement(values: RequirementFormValues) {
    setSaving(true);
    setStatusMessage(null);
    try {
      const response = await fetch("/api/requirements", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (response.status === 401) {
        replace("/login");
        return { ok: false as const, message: "登录已失效，正在返回登录页。" };
      }
      if (!response.ok) {
        return { ok: false as const, message: "需求未保存，请检查编号或关联客户。" };
      }
      const created = await readRequirement(response);
      setRequirements((current) => [created, ...current]);
      setCreating(false);
      setStatusMessage("需求已创建");
      return { ok: true as const };
    } catch {
      return { ok: false as const, message: "网络连接失败，请稍后重试。" };
    } finally {
      setSaving(false);
    }
  }

  async function convertRequirement(
    requirement: Requirement,
    values: RequirementConversionValues,
  ) {
    setSaving(true);
    setStatusMessage(null);
    try {
      const response = await fetch(`/api/requirements/${requirement.id}/convert-to-case`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (response.status === 401) {
        replace("/login");
        return { ok: false as const, message: "登录已失效，正在返回登录页。" };
      }
      if (!response.ok) {
        return { ok: false as const, message: "转化未完成，请检查需求状态或案例编号。" };
      }
      const body = await responseBody(response);
      if (
        !isRecord(body) ||
        !isRecord(body.development_case) ||
        typeof body.development_case.id !== "string"
      ) {
        return { ok: false as const, message: "转化响应无效，请稍后重试。" };
      }
      setRequirements((current) =>
        current.map((item) =>
          item.id === requirement.id ? { ...item, status: "converted" as const } : item,
        ),
      );
      setConvertingId(null);
      push("/cases");
      return { ok: true as const };
    } catch {
      return { ok: false as const, message: "网络连接失败，请稍后重试。" };
    } finally {
      setSaving(false);
    }
  }

  async function updateRequirement(
    requirement: Requirement,
    values: RequirementFormValues,
  ) {
    const patch: Record<string, unknown> = {};
    const currentValues = {
      code: requirement.code,
      title: requirement.title,
      customer_id: requirement.customer?.id ?? null,
      priority: requirement.priority,
      source: requirement.source,
      description: requirement.description,
      acceptance_criteria: requirement.acceptance_criteria,
      status: requirement.status,
    };
    for (const [key, value] of Object.entries(values)) {
      if (JSON.stringify(value) !== JSON.stringify(currentValues[key as keyof typeof currentValues])) {
        patch[key] = value;
      }
    }
    if (Object.keys(patch).length === 0) {
      setEditingId(null);
      setStatusMessage("没有需要保存的更改");
      return { ok: true as const };
    }
    setSaving(true);
    setStatusMessage(null);
    try {
      const response = await fetch(`/api/requirements/${requirement.id}`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (response.status === 401) {
        replace("/login");
        return { ok: false as const, message: "登录已失效，正在返回登录页。" };
      }
      if (!response.ok) {
        return { ok: false as const, message: "需求未更新，请检查字段或关联客户。" };
      }
      const updated = await readRequirement(response);
      setRequirements((current) =>
        current
          .map((item) => (item.id === updated.id ? updated : item))
          .sort((left, right) => right.updated_at.localeCompare(left.updated_at)),
      );
      setEditingId(null);
      setStatusMessage("需求已更新");
      return { ok: true as const };
    } catch {
      return { ok: false as const, message: "网络连接失败，请稍后重试。" };
    } finally {
      setSaving(false);
    }
  }

  async function reviewCrmRequirement(
    requirement: Requirement,
    decision: "establish" | "reject",
    rationale: string,
  ) {
    setSaving(true);
    setStatusMessage(null);
    try {
      const response = await fetch(
        `/api/requirements/${requirement.id}/review-crm-intake`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            confirmation: "REVIEW_CONFIRMED",
            decision,
            rationale,
          }),
        },
      );
      if (response.status === 401) {
        replace("/login");
        return { ok: false as const, message: "登录已失效，正在返回登录页。" };
      }
      if (!response.ok) {
        return { ok: false as const, message: "CRM 草稿人审未完成，请刷新后重试。" };
      }
      const updated = await readRequirement(response);
      setRequirements((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setEditingId(null);
      setStatusMessage(decision === "establish" ? "CRM 需求已成立" : "CRM 草稿已拒绝");
      return { ok: true as const };
    } catch {
      return { ok: false as const, message: "网络连接失败，请稍后重试。" };
    } finally {
      setSaving(false);
    }
  }

  return {
    beginConversion(requirement: Requirement) {
      setCreating(false);
      setEditingId(null);
      setConvertingId(requirement.id);
    },
    cancelConversion: () => setConvertingId(null),
    cancelCreate: () => setCreating(false),
    cancelEdit: () => setEditingId(null),
    convertingRequirement,
    createRequirement,
    creating,
    editingRequirement,
    convertRequirement,
    requirements,
    reviewCrmRequirement,
    saving,
    selectRequirement(requirement: Requirement) {
      setCreating(false);
      setConvertingId(null);
      setEditingId(requirement.id);
    },
    setRequirements,
    startCreate() {
      setEditingId(null);
      setConvertingId(null);
      setCreating(true);
    },
    statusMessage,
    updateRequirement,
  };
}
