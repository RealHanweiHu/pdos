"use client";

import { type FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

import {
  addProjectMember,
  type MemberCandidate,
  removeProjectMember,
  requestMemberCandidates,
} from "./project-member-api";
import type { ProjectMember } from "./project-work-item-types";

export const roleLabels: Record<string, string> = {
  owner: "所有者",
  admin: "管理员",
  project_manager: "项目经理",
  engineer: "工程师",
  quality: "质量",
  supplier: "供应商",
  customer: "客户",
};

const controlClass =
  "min-h-11 w-full min-w-0 rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:opacity-60";

export function ProjectMembersCard({
  canManage,
  currentUserId,
  members,
  onMembersChange,
  ownerUserId,
  projectId,
}: {
  canManage: boolean;
  currentUserId: string;
  members: ProjectMember[];
  onMembersChange: (members: ProjectMember[]) => void;
  ownerUserId: string;
  projectId: string;
}) {
  const [candidates, setCandidates] = useState<MemberCandidate[] | null>(null);
  const [selected, setSelected] = useState("");
  const [confirmingUserId, setConfirmingUserId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => {
    if (!canManage) return;
    let active = true;
    requestMemberCandidates(projectId).then(
      (loaded) => { if (active) setCandidates(loaded); },
      () => { if (active) setCandidates([]); },
    );
    return () => { active = false; };
  }, [canManage, projectId]);

  async function run(operation: () => Promise<ProjectMember[]>, success: string) {
    setBusy(true);
    setError(null);
    setStatus(null);
    try {
      onMembersChange(await operation());
      setCandidates(await requestMemberCandidates(projectId).catch(() => candidates ?? []));
      setStatus(success);
      return true;
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "成员操作失败，请稍后重试。");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected) return;
    if (await run(() => addProjectMember(projectId, selected), "成员已添加")) setSelected("");
  }

  async function remove(member: ProjectMember) {
    await run(() => removeProjectMember(projectId, member.user_id), `已移除 ${member.display_name}`);
    setConfirmingUserId(null);
  }

  return (
    <section aria-label="项目成员" className="overflow-hidden rounded-lg border bg-card">
      <div className="flex items-center justify-between gap-3 border-b px-4 py-3">
        <h3 className="font-semibold">项目成员</h3>
        <span className="font-mono text-[11px] text-muted-foreground">{members.length} 人</span>
      </div>
      <ul className="divide-y" role="list">
        {members.map((member) => {
          const confirming = confirmingUserId === member.user_id;
          return (
            <li className="flex min-h-11 flex-wrap items-center gap-2 px-4 py-2" key={member.user_id}>
              <span className="min-w-0 flex-1 truncate text-sm">
                {member.display_name}
                {member.user_id === currentUserId ? <span className="text-muted-foreground">（我）</span> : null}
              </span>
              <span className="rounded-full border bg-muted px-2 py-0.5 text-[10px] text-muted-foreground">{roleLabels[member.role] ?? member.role}</span>
              {member.user_id === ownerUserId ? (
                <span className="rounded-full border border-primary/25 bg-primary/10 px-2 py-0.5 text-[10px] text-primary">项目负责人</span>
              ) : null}
              {!member.is_active ? <span className="text-[10px] text-muted-foreground">已停用</span> : null}
              {canManage && member.user_id !== ownerUserId && !confirming ? (
                <Button aria-label={`移除成员 ${member.display_name}`} className="h-11 sm:h-7" disabled={busy} onClick={() => setConfirmingUserId(member.user_id)} size="sm" variant="ghost">
                  移除
                </Button>
              ) : null}
              {confirming ? (
                <span className="flex w-full flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  移除后对方将无法访问此项目。
                  <Button className="h-11 sm:h-7" disabled={busy} onClick={() => void remove(member)} size="sm" variant="destructive">确认移除</Button>
                  <Button className="h-11 sm:h-7" disabled={busy} onClick={() => setConfirmingUserId(null)} size="sm" variant="outline">取消</Button>
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
      {canManage ? (
        <form className="flex flex-col gap-2 border-t p-3 sm:flex-row sm:items-end" onSubmit={add}>
          <label className="min-w-0 flex-1 text-xs font-medium" htmlFor={`member-candidate-${projectId}`}>
            添加成员
            <select
              className={`${controlClass} mt-1`}
              disabled={busy || !candidates || candidates.length === 0}
              id={`member-candidate-${projectId}`}
              onChange={(event) => setSelected(event.target.value)}
              value={selected}
            >
              <option value="">{candidates === null ? "正在读取…" : candidates.length === 0 ? "没有可添加的用户" : "选择用户"}</option>
              {(candidates ?? []).map((candidate) => (
                <option key={candidate.user_id} value={candidate.user_id}>
                  {candidate.display_name} · {roleLabels[candidate.role] ?? candidate.role}
                </option>
              ))}
            </select>
          </label>
          <Button className="h-11" disabled={busy || !selected} type="submit">添加</Button>
        </form>
      ) : null}
      {error ? <p className="border-t px-4 py-2 text-xs text-destructive" role="alert">{error}</p> : null}
      {status ? <p className="border-t px-4 py-2 text-xs text-muted-foreground" role="status">{status}</p> : null}
    </section>
  );
}
