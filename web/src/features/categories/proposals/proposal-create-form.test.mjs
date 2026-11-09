import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { setImmediate as tick } from "node:timers/promises";

const require = createRequire(import.meta.url);
const ts = require("typescript");

function compile(file, imports, storage) {
  const source = new URL(file, import.meta.url);
  const { outputText } = ts.transpileModule(readFileSync(source, "utf8"), {
    fileName: source.pathname,
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  });
  const exports = {};
  const load = name => imports[name] ?? require(name);
  new Function("require", "exports", "crypto", "sessionStorage", outputText)(
    load, exports, { randomUUID }, storage,
  );
  return exports;
}

function mount(props, storage) {
  let index = 0;
  let cleanup;
  const slots = [];
  const react = {
    useState(initial) {
      const slot = index++;
      if (!(slot in slots)) slots[slot] = initial;
      return [slots[slot], value => { slots[slot] = value; }];
    },
    useRef(initial) { return slots[index++] ??= { current: initial }; },
    useEffect(effect) { cleanup ??= effect(); },
  };
  const { ProposalCreateForm } = compile("./proposal-create-form.tsx", {
    react,
    "@/components/ui/button": { Button: "button" },
    "@/lib/category-transport": compile("../../../lib/category-transport.ts", {}),
  }, storage);
  const render = () => { index = 0; return ProposalCreateForm(props); };
  return { render, unmount: () => cleanup?.() };
}

function nodes(tree) {
  if (Array.isArray(tree)) return tree.flatMap(nodes);
  return tree?.props ? [tree, ...nodes(tree.props.children)] : [];
}

function button(view, label) {
  return nodes(view.render()).find(node => node.type === "button" && node.props.children === label);
}

test("a lost creation receipt survives refresh and retries the same sealed command", async () => {
  const stored = new Map();
  const storage = {
    getItem: key => stored.get(key) ?? null,
    setItem: (key, value) => stored.set(key, value),
    removeItem: key => stored.delete(key),
  };
  const categoryId = randomUUID(), subjectId = randomUUID();
  const submitted = [], opened = [];
  const props = {
    categoryId, principalId: randomUUID(), onCreated: id => opened.push(id),
    async api(path, body) {
      if (path === "v1/categories") return [{ id: categoryId, revision: 1 }];
      if (path.endsWith("/preview")) return {
        command: { ...body, payload: { ...body.payload, confirmation_token: "server-proof" } },
        confirmation_token: "server-proof", expires_at: null,
      };
      submitted.push(body);
      if (submitted.length === 1) throw new Error("connection closed after commit");
      return { id: randomUUID(), category_id: categoryId, operation: "proposal.create",
        subject_type: "proposal", subject_id: subjectId };
    },
  };
  const before = mount(props, storage);
  before.render();
  await tick();
  nodes(before.render()).find(node => node.type === "input").props.onChange({
    target: { value: "合成提案" },
  });
  button(before, "查看创建预览").props.onClick();
  await tick();
  button(before, "本人确认并创建提案").props.onClick();
  await tick();
  assert.equal(stored.size, 1);
  before.unmount();

  const after = mount(props, storage);
  after.render();
  await tick();
  assert.equal(button(after, "查看创建预览"), undefined);
  button(after, "使用原请求核对").props.onClick();
  await tick();
  assert.equal(submitted.length, 2);
  assert.deepEqual(submitted[1], submitted[0]);
  assert.deepEqual(opened, [subjectId]);
  assert.equal(stored.size, 0);
});
