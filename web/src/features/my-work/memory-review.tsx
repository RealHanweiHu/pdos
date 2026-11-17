"use client";

/* 我的工作 · 要我复核（记忆）: one card per item. Facts are fixed in the business object, not in
   memory; a personal card becomes a note only when I click 记下; a team card is saved on the
   team memo (scope_note.save, audience shown there) and dismissed or marked here. My own
   corrections can add a personal card, propose a team note, or go to the object's owner. */
import { useState } from "react";
import { ArrowBendUpRight, ClockCounterClockwise, NotePencil, UsersThree, WarningCircle } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  decisionLabels, proposedKindLabels, requestKey, reviewDecisionPath, reviewRoutePath, routeChoices,
  type MemoryReviewApi, type ReviewItem,
} from "@/features/my-work/lib/memory-review";
import styles from "./run-decisions.module.css";

const icons = {
  fact: WarningCircle, skill: NotePencil, personal: NotePencil, team: UsersThree,
  object_updated: ClockCounterClockwise, author_departed: ArrowBendUpRight,
};
const routeLabels = { personal: "记为个人条目", team: "提议团队备忘", forward: "转给对象负责人" };

function detail(item: ReviewItem) {
  if (item.kind === "object_updated" && item.object) return `${item.object.title ?? "引用的对象"}：记下时第 ${item.object.recorded_version ?? "?"} 版，现在第 ${item.object.current_version ?? "?"} 版。`;
  if (item.kind === "author_departed") return "作者已离开，这条团队备忘的复核转给你。";
  if (item.kind === "fact") return item.object?.title ? `涉及：${item.object.title}。请在业务对象或原件上改正，记忆不替事实打补丁。` : "请在业务对象或原件上改正，记忆不替事实打补丁。";
  if (item.kind === "team") return "在对应页面的团队备忘区记下这一条（会显示受众），记下后这里标为已处理。";
  return null;
}

function ReviewCard({ api, item, onChanged }: { api: MemoryReviewApi; item: ReviewItem; onChanged: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const Icon = icons[item.kind];
  const decide = async (decision: string) => {
    setBusy(true); setError("");
    try { await api(reviewDecisionPath(item.item_id), { request_key: requestKey(), decision }); onChanged(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "没有处理成功。"); }
    finally { setBusy(false); }
  };
  // A team card is marked adopted only with the note saved through scope_note.save.
  const choices = item.choices.filter(choice => !(item.kind === "team" && choice === "adopted"));
  return (
    <article className={styles.card} aria-label={item.label}>
      <div className={styles.heading}>
        <Icon size={15} aria-hidden/>
        <div><h3>{item.label}</h3><p>{new Date(item.recorded_at).toLocaleString("zh-CN")}</p></div>
      </div>
      {item.text && <p className={styles.note}>{item.proposed_kind ? `${proposedKindLabels[item.proposed_kind] ?? ""}：` : ""}{item.text}</p>}
      {detail(item) && <p className={styles.note}>{detail(item)}</p>}
      {choices.length > 0 && (
        <div className={styles.actions}>
          {choices.map(choice => (
            <Button key={choice} size="sm" variant={choice === "dismissed" ? "ghost" : "outline"} disabled={busy} onClick={() => decide(choice)}>
              {decisionLabels[choice] ?? choice}
            </Button>
          ))}
        </div>
      )}
      {error && <p className={styles.error} role="alert">{error}</p>}
    </article>
  );
}

function RouteForm({ api, item, onChanged }: { api: MemoryReviewApi; item: ReviewItem; onChanged: () => void }) {
  const [route, setRoute] = useState<"personal" | "team" | "forward" | null>(null);
  const [text, setText] = useState("");
  const [kind, setKind] = useState("convention");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const choices = routeChoices(item);
  if (!choices.length) return null;
  const limit = route === "personal" ? 200 : 300;
  const submit = async () => {
    if (!route) return;
    setBusy(true); setError("");
    try {
      await api(reviewRoutePath(item.item_id), {
        request_key: requestKey(), route, text: text.trim() || null,
        kind: route === "forward" ? null : kind, scope: "run",
      });
      setRoute(null); setText(""); onChanged();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "没有分流成功。"); }
    finally { setBusy(false); }
  };
  return (
    <div className={styles.block}>
      <div className={styles.actions}>
        {choices.map(choice => (
          <Button key={choice} size="sm" variant={route === choice ? "secondary" : "ghost"} onClick={() => setRoute(route === choice ? null : choice)}>{routeLabels[choice]}</Button>
        ))}
      </div>
      {route && (
        <>
          {route !== "forward" && (
            <label className={styles.note}>种类{" "}
              <select value={kind} onChange={event => setKind(event.target.value)}>
                {(route === "personal" ? ["convention", "background"] : ["convention", "concern", "decision_context", "observation"]).map(value => (
                  <option key={value} value={value}>{proposedKindLabels[value]}</option>
                ))}
              </select>
            </label>
          )}
          <textarea aria-label="用你自己的话写" maxLength={limit} rows={2} value={text} onChange={event => setText(event.target.value)}
            placeholder={route === "forward" ? "给对象负责人的说明（可选）" : "用你自己的话写这一条"}/>
          <div className={styles.actions}>
            <Button size="sm" disabled={busy || (route !== "forward" && !text.trim())} onClick={submit}>提交</Button>
            <span>{route === "personal" ? "生成提议卡，你点“记下”后才写入。" : route === "team" ? "生成待确认候选，由挂靠对象负责人确认。" : "对象负责人会在“我的工作”里看到。"}</span>
          </div>
        </>
      )}
      {error && <p className={styles.error} role="alert">{error}</p>}
    </div>
  );
}

export function MemoryReview({ api, items, raised, onChanged }: { api: MemoryReviewApi; items: ReviewItem[]; raised: ReviewItem[]; onChanged: () => void }) {
  const mine = raised.filter(item => item.source === "correction" && !item.parent_id);
  return (
    <div className={styles.list}>
      {items.map(item => <ReviewCard key={item.item_id} api={api} item={item} onChanged={onChanged}/>)}
      {mine.slice(0, 5).map(item => (
        <article key={item.item_id} className={styles.card} aria-label={`我的纠正：${item.label}`}>
          <div className={styles.heading}>
            <NotePencil size={15} aria-hidden/>
            <div><h3>我的纠正 · {item.label}</h3><p>{decisionLabels[item.status] ?? "待处理"} · {new Date(item.recorded_at).toLocaleString("zh-CN")}</p></div>
          </div>
          <RouteForm api={api} item={item} onChanged={onChanged}/>
        </article>
      ))}
    </div>
  );
}
