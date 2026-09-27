"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
import type { UserRole } from "@/components/users/user-management-types";

type Member = {
  user_id: string;
  username: string;
  display_name: string;
  role: UserRole;
  is_active: boolean;
  added_by_display_name: string;
  created_at: string;
  is_owner: boolean;
  removal_blocker: string | null;
};
type Candidate = { user_id: string; username: string; display_name: string; role: UserRole };
type Roster = { can_manage: boolean; access_lost?: boolean; items: Member[]; available_users: Candidate[]; receipt?: { replayed: boolean } };

const roleLabels: Record<UserRole, string> = {
  owner: "租户所有者",
  admin: "租户管理员",
  project_manager: "项目经理",
  engineer: "工程师",
  quality: "品质",
  supplier: "供应商",
  customer: "客户",
};
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";

/** Server messages for member conflicts are already Chinese; transport failures are not. */
function failure(status: number, body: unknown): string {
  if (status === 401) return "登录已失效，请重新登录";
  if (status === 403) return "当前没有办理本项目成员的权限";
  if (status >= 500) return "项目成员服务暂不可用，请稍后重试";
  const detail = isRecord(body) && isRecord(body.detail) ? body.detail : null;
  return typeof detail?.message === "string" ? detail.message : "项目成员操作未完成";
}

export function ProjectMembers({ projectId, userId }: { projectId: string; userId: string }) {
  const [data, setData] = useState<Roster | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [candidate, setCandidate] = useState("");
  const [confirming, setConfirming] = useState<Member | null>(null);
  // A request id is kept only while its outcome is unknown, so a retry after a
  // lost response replays instead of acting twice; any definite answer drops it.
  const pending = useRef(new Map<string, string>());
  const base = `/api/projects/${encodeURIComponent(projectId)}/members`;

  async function read(response: Response): Promise<Roster> {
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) setData(null);
      throw new Error(failure(response.status, body));
    }
    if (!isRecord(body) || !Array.isArray(body.items) || !Array.isArray(body.available_users) || typeof body.can_manage !== "boolean") {
      throw new Error("未收到完整回执；请重试核对办理结果");
    }
    return body as Roster;
  }

  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "项目成员暂不可用");
    } finally {
      setBusy(false);
    }
  }

  async function command(key: string, url: string, body: Record<string, string>) {
    let requestId = pending.current.get(key);
    if (!requestId) {
      requestId = crypto.randomUUID();
      pending.current.set(key, requestId);
    }
    let response: Response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, request_id: requestId }),
      });
    } catch {
      throw new Error("网络中断；重试将沿用同一请求，不会重复办理");
    }
    if (!response.ok && response.status < 500) pending.current.delete(key);
    if (response.status === 404 || response.status === 409) {
      // Someone else changed the roster first: show their result, not a stale list.
      const message = failure(response.status, await response.json().catch(() => null));
      await load().catch(() => undefined);
      throw new Error(message);
    }
    const result = await read(response);
    pending.current.delete(key);
    setData(result);
    return result;
  }

  async function load() {
    setData(await read(await fetch(base, { cache: "no-store" })));
  }

  const add = (target: Candidate) =>
    act(async () => {
      const result = await command(`add:${target.user_id}`, base, { user_id: target.user_id });
      setCandidate("");
      setNotice(result.receipt?.replayed
        ? "已核对原添加回执；当前成员状态以名单为准。"
        : `已将 ${target.display_name} 加入项目。`);
    });

  const remove = (member: Member) =>
    act(async () => {
      try {
        const result = await command(
          `remove:${member.user_id}`,
          `${base}/${encodeURIComponent(member.user_id)}/remove`,
          {},
        );
        setNotice(result.access_lost
          ? "你已移出本项目，项目访问权限已收回。"
          : result.receipt?.replayed
            ? "已核对原移出回执；当前成员状态以名单为准。"
            : `已将 ${member.display_name} 移出项目。`);
      } finally {
        setConfirming(null);
      }

    });

  const selected = data?.available_users.find((user) => user.user_id === candidate) ?? null;

  return (
    <details
      className="mt-6 rounded-lg border p-4 text-sm"
      onToggle={(event) => {
        if (event.currentTarget.open && data === null && !busy) void act(load);
      }}
    >
      <summary className="cursor-pointer font-semibold">
        项目成员{data ? ` · ${data.items.length} 人` : ""}
      </summary>
      <p className="mt-2 text-muted-foreground">
        成员资格决定谁能进入本项目；能办理哪些事项仍由各自岗位权限决定。
      </p>
      {error ? <p className="mt-3 text-destructive" role="alert">{error}</p> : null}
      {notice ? <p className="mt-3 text-success" role="status">{notice}</p> : null}
      {data === null && busy ? <p className="mt-3 text-muted-foreground">正在读取项目成员…</p> : null}
      {data === null && !busy && error ? (
        <Button className="mt-3" onClick={() => void act(load)} size="sm" type="button" variant="outline">
          重新读取成员
        </Button>
      ) : null}
      {data && !data.access_lost ? (
        <>
          <Button className="mt-3" disabled={busy} onClick={() => void act(load)} size="sm" type="button" variant="ghost">刷新成员</Button>
          <ul className="mt-3 divide-y rounded-md border" aria-label="项目成员名单">
            {data.items.map((member) => (
              <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2" key={member.user_id}>
                <div className="min-w-0 flex-1">
                  <p className="font-medium">
                    {member.display_name}
                    <span className="ml-1 font-mono text-xs text-muted-foreground">{member.username}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {roleLabels[member.role] ?? member.role}
                    {member.is_owner ? " · 项目负责人" : ""}
                    {member.is_active ? "" : " · 账号已停用"}
                    {` · 由 ${member.added_by_display_name} 于 ${new Date(member.created_at).toLocaleDateString()} 加入`}
                  </p>
                </div>
                {data.can_manage && member.removal_blocker ? (
                  <span className="text-xs text-muted-foreground">{member.removal_blocker}</span>
                ) : null}
                {data.can_manage && !member.removal_blocker ? (
                  <Button
                    disabled={busy}
                    onClick={() => { setConfirming(member); setNotice(""); }}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    移出项目
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
          {confirming ? (
            <div className="mt-3 space-y-2 rounded-md border border-destructive/30 bg-destructive/5 p-3" role="group" aria-label="确认移出成员">
              <p>
                确认将 {confirming.display_name} 移出项目？移出后将收回其直接成员资格；租户管理员或有效代理仍可能有访问权，已分派给其的工作不会自动转交。
                {confirming.user_id === userId ? "你正在移出自己。" : ""}
              </p>
              <div className="flex gap-2">
                <Button disabled={busy} onClick={() => void remove(confirming)} size="sm" type="button" variant="destructive">
                  确认移出
                </Button>
                <Button disabled={busy} onClick={() => setConfirming(null)} size="sm" type="button" variant="ghost">
                  取消
                </Button>
              </div>
            </div>
          ) : null}
          {data.can_manage ? (
            data.available_users.length > 0 ? (
              <form
                className="mt-3 flex flex-wrap items-end gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (selected) void add(selected);
                }}
              >
                <label className="min-w-0 basis-56 flex-1">
                  添加成员
                  <select className={field} disabled={busy} onChange={(event) => setCandidate(event.target.value)} required value={candidate}>
                    <option value="">请选择在岗内部成员</option>
                    {data.available_users.map((user) => (
                      <option key={user.user_id} value={user.user_id}>
                        {user.display_name}（{user.username}）· {roleLabels[user.role] ?? user.role}
                      </option>
                    ))}
                  </select>
                </label>
                <Button disabled={busy || !selected}>加入项目</Button>
              </form>
            ) : (
              <p className="mt-3 text-muted-foreground">没有可添加的在岗内部成员。</p>
            )
          ) : (
            <p className="mt-3 text-muted-foreground">成员调整由本项目的项目经理或租户管理员办理。</p>
          )}
        </>
      ) : null}
    </details>
  );
}
