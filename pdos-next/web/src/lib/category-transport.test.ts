import assert from "node:assert/strict";
import test from "node:test";
import { categoryTransport } from "./category-transport";
import type { WorkspaceTransport } from "./workspace-api";

test("model input and preview ports carry the selected category on the full command envelope", async () => {
  const calls: { path: string; body: unknown }[] = [];
  const transport: WorkspaceTransport = async <T>(path: string, body?: unknown): Promise<T> => {
    calls.push({ path, body });
    return { command: body } as T;
  };
  const scoped = categoryTransport("chosen-category", transport);
  const command = { command_id: "id", operation: "npi.work_instruction.record", payload: {} };
  for (const path of ["v1/products/model/manufacturing-preparation/inputs", "v1/commands/preview"]) {
    const value = await scoped<{ command: Record<string, unknown> }>(path, command);
    assert.equal(value.command.category_id, "chosen-category");
  }
  assert.deepEqual(calls.map(c => c.path), [
    "v1/categories/chosen-category/products/model/manufacturing-preparation/inputs",
    "v1/categories/chosen-category/commands/preview",
  ]);
  assert.equal("category_id" in command, false);
});

test("ordinary strict inputs stay intact and existing category URLs cannot cross the selected scope", async () => {
  let count = 0;
  const transport: WorkspaceTransport = async <T>(_path: string, body?: unknown): Promise<T> => {
    count += 1;
    return body as T;
  };
  const scoped = categoryTransport("one", transport);
  const input = { name: "New category", confirmed: true };
  assert.equal(await scoped("v1/categories/one/members", input), input);
  await assert.rejects(scoped("v1/categories/two/products"));
  assert.equal(count, 1);
});

test("a returned command for another category is rejected before it becomes a local pending action", async () => {
  const scoped = categoryTransport("one", (async () => ({ command: { category_id: "two" } })) as WorkspaceTransport);
  await assert.rejects(scoped("v1/commands/preview", {
    command_id: "id", operation: "change.order.approve", payload: {},
  }));
});
