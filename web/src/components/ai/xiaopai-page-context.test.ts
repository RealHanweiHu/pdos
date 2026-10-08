import { expect, it } from "vitest";
import { resolveXiaopaiPageContext } from "./xiaopai-page-context";
const category = "20000000-0000-4000-8000-000000000001";
it("binds canonical category links and retains the old deep link scope", () => {
  const canonical = resolveXiaopaiPageContext("/product-work", new URLSearchParams({ category, tab:"proposals" }));
  const legacy = resolveXiaopaiPageContext("/product-work", new URLSearchParams({ space:category, tab:"proposals" }));
  expect(canonical.productScope).toEqual(legacy.productScope);
  expect(canonical.spaceId).toBe(category);
  expect(canonical.scopeError).toBeUndefined();
  expect(resolveXiaopaiPageContext("/product-work", new URLSearchParams({ category:"bad" })).productScope).toBeUndefined();
});
