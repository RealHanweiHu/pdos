import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json")), ts = dependency("typescript");
const filename = path.join(directory, "discussions.ts"), loaded = new Module(filename);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const { segments, mentionToken, activeQuery, insertMention, mentionChoices, anchorLabel, mentionError, commentsPath, mentionablePath, hasAgentMention, cardInProgress, cardTone, cardNote, agentReplyPath, agentSharePath } = loaded.exports;

const peer = "00000000-0000-4000-8000-000000000002", outsider = "00000000-0000-4000-8000-000000000003", me = "00000000-0000-4000-8000-000000000001";

test("tokens render with current names and keep plain text intact", () => {
  const body = `请 ${mentionToken("person", "旧名", peer)} 和 @[品质](role:quality) 看 @[任务](task:${peer})，邮箱 a@b.c 不是提及`;
  const parts = segments(body, { [peer]: "许晴" });
  assert.deepEqual(parts.filter(part => part.kind === "mention").map(part => [part.mention, part.label]), [["person", "许晴"], ["role", "品质"], ["task", "任务"]]);
  assert.equal(parts.filter(part => part.kind === "text").map(part => part.text).join(""), "请  和  看 ，邮箱 a@b.c 不是提及");
  assert.equal(mentionToken("all", "全体"), "@[全体](all)");
  assert.equal(mentionToken("person", "a]b", peer), `@[ab](person:${peer})`);
});

test("the @ query is only active at a word start and is replaced on insert", () => {
  assert.deepEqual(activeQuery("你好 @许", 5), { start: 3, query: "许" });
  assert.equal(activeQuery("mail a@b", 8), null);
  assert.equal(activeQuery("@许 晴", 5), null);
  const inserted = insertMention("你好 @许", 5, mentionToken("person", "许晴", peer));
  assert.equal(inserted.text, `你好 @[许晴](person:${peer}) `);
  assert.equal(inserted.caret, inserted.text.length);
});

test("people who cannot see the object stay listed but disabled; @全体 only for the owner", () => {
  const options = {
    people: [
      { principal_id: me, name: "本人", is_member: true, roles: [], can_see: true, is_self: true },
      { principal_id: outsider, name: "陈舟", is_member: false, roles: [], can_see: false, is_self: false },
      { principal_id: peer, name: "许晴", is_member: true, roles: ["品质"], can_see: true, is_self: false },
    ],
    roles: [{ key: "quality", name: "品质", members: 1 }], can_mention_all: false, can_invite: true, agent: { available: false, note: "" },
  };
  const choices = mentionChoices(options, "");
  // 小Pai stays listed first, greyed like people who cannot see the object (D37 ⑥).
  assert.deepEqual(choices.map(choice => [choice.label, choice.disabled]), [["小Pai", true], ["许晴", false], ["陈舟", true], ["品质", false]]);
  assert.match(choices[2].reason, /提及不授予访问权/);
  assert.equal(choices[2].detail, "不在本项目受众中");
  assert.deepEqual(mentionChoices(options, "品").map(choice => choice.label), ["许晴", "品质"]);
  assert.equal(mentionChoices({ ...options, can_mention_all: true }, "全").at(-1).token, "@[全体](all)");
});

test("anchors, paths and refusal text", () => {
  const message = { subject_revision: 2 };
  assert.equal(anchorLabel(message, { revision: 2 }), "评论于 v2");
  assert.equal(anchorLabel(message, { revision: 4 }), "评论于 v2 · 当前 v4");
  assert.equal(anchorLabel({ subject_revision: null }, null), null);
  assert.equal(mentionError({ detail: { reason: "mention_not_visible", blocked: [{ name: "陈舟" }] } }), "不在本项目受众中：陈舟。提及不授予访问权。");
  assert.equal(mentionError(new Error("x")), null);
  const scope = { categoryId: "c", productId: "p", projectId: "j" };
  assert.equal(commentsPath(scope, "work_task", "t"), "v1/categories/c/products/p/projects/j/comments/work_task/t");
  assert.equal(mentionablePath(scope), "v1/categories/c/products/p/projects/j/mentionable");
  assert.equal(mentionablePath(scope, "work_task", "t"), "v1/categories/c/products/p/projects/j/mentionable?subject_type=work_task&subject_id=t");
});

test("@小Pai is offered first, greyed when unavailable, and marks a message that starts a run", () => {
  const options = { people: [{ principal_id: peer, name: "许晴", is_member: true, roles: [], can_see: true, is_self: false }], roles: [], can_mention_all: false, can_invite: false, agent: { available: true, note: "按你的权限运行" } };
  const all = mentionChoices(options, "");
  assert.deepEqual(all.map(choice => [choice.kind, choice.label, choice.disabled]), [["agent", "小Pai", false], ["person", "许晴", false]]);
  assert.equal(all[0].token, "@[小Pai](agent)");
  assert.deepEqual(mentionChoices(options, "pai").map(choice => choice.kind), ["agent"]);
  assert.deepEqual(mentionChoices(options, "许").map(choice => choice.kind), ["person"]);
  const off = mentionChoices({ ...options, agent: { available: false, note: "小Pai 当前不可用" } }, "小");
  assert.equal(off[0].disabled, true);
  assert.equal(off[0].reason, "小Pai 当前不可用");
  assert.equal(hasAgentMention("@[小Pai](agent) 总结一下"), true);
  assert.equal(hasAgentMention("@[小Pai](agent:xiaopai) 总结"), true);
  assert.equal(hasAgentMention(`请 ${mentionToken("person", "许晴", peer)} 看`), false);
  assert.deepEqual(segments("@[小Pai](agent) 看看").map(part => part.kind === "mention" ? part.mention : part.text), ["agent", " 看看"]);
  assert.equal(mentionError({ detail: { reason: "agent_mention_edit" } }), "编辑不会发起小Pai，请另发一条消息 @小Pai。");
});

test("run cards say where the reply went without naming any hidden source", () => {
  const card = { request_id: run(), requester_name: "许晴", own: false, state: "running", label: "进行中", delivery: "pending", reason: null, reason_label: null, private_only: false, reply_message_id: null, share_mode: null, can_open_link: false };
  assert.equal(cardInProgress(card), true);
  assert.equal(cardTone(card), "running");
  assert.equal(cardTone({ ...card, state: "waiting_input" }), "waiting");
  const settled = { ...card, state: "completed", label: "完成", delivery: "private", reason: "audience_not_covered", reason_label: "这次读取的部分来源，串里有人看不到" };
  assert.equal(cardInProgress(settled), false);
  assert.equal(cardTone(settled), "done");
  assert.equal(cardNote(settled), "回复只给许晴看：这次读取的部分来源，串里有人看不到。");
  assert.equal(cardNote({ ...settled, own: true, share_mode: "link" }), "你已分享回复链接；成员打开时按各自权限核对全部来源。");
  assert.equal(cardNote({ ...settled, share_mode: "link", can_open_link: true }), "许晴分享了回复链接；打开前按你的权限核对全部来源。");
  assert.equal(cardNote({ ...settled, share_mode: "body" }), "许晴已把回复正文分享到串里。");
  assert.equal(cardNote({ ...settled, delivery: "public", own: false }), null);
  assert.equal(cardNote({ ...settled, state: "failed", delivery: "none", reason: "run_failed", reason_label: "这次运行失败了" }), "这次运行失败了。");
  assert.equal(cardTone({ ...settled, state: "failed", delivery: "none" }), "failed");
  assert.equal(cardNote({ ...card, own: true, state: "waiting_input" }), "小Pai 需要你补充信息，请在小Pai 工作栏里回答。");
  const scope = { categoryId: me, productId: peer, projectId: outsider };
  assert.equal(agentReplyPath(scope, peer, me), `v1/categories/${me}/products/${peer}/projects/${outsider}/discussions/${peer}/agent-requests/${me}/reply`);
  assert.equal(agentSharePath(scope, peer, me).endsWith(`/agent-requests/${me}/share`), true);
});

function run() { return "00000000-0000-4000-8000-000000000009"; }
