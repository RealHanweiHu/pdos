import { describe, expect, it } from "vitest";

import { FixedWindowRateLimiter, loginRateLimitKey } from "./login-rate-limit";

describe("FixedWindowRateLimiter", () => {
  it("blocks attempts beyond the limit until the window expires", () => {
    const limiter = new FixedWindowRateLimiter({ limit: 2, windowMs: 1_000 });

    expect(limiter.consume("identity", 0)).toEqual({ allowed: true });
    expect(limiter.consume("identity", 100)).toEqual({ allowed: true });
    expect(limiter.consume("identity", 200)).toEqual({
      allowed: false,
      retryAfterSeconds: 1,
    });
    expect(limiter.consume("identity", 1_000)).toEqual({ allowed: true });
  });

  it("refunds upstream failures and clears a successful identity", () => {
    const limiter = new FixedWindowRateLimiter({ limit: 1, windowMs: 10_000 });

    expect(limiter.consume("identity", 0)).toEqual({ allowed: true });
    limiter.refund("identity");
    expect(limiter.consume("identity", 1)).toEqual({ allowed: true });
    limiter.clear("identity");
    expect(limiter.consume("identity", 2)).toEqual({ allowed: true });
  });

  it("fails closed when the bounded identity table is full", () => {
    const limiter = new FixedWindowRateLimiter({
      limit: 2,
      maxTrackedKeys: 2,
      windowMs: 1_000,
    });

    expect(limiter.consume("one", 0)).toEqual({ allowed: true });
    expect(limiter.consume("two", 0)).toEqual({ allowed: true });
    expect(limiter.consume("three", 100)).toEqual({
      allowed: false,
      retryAfterSeconds: 1,
    });
    expect(limiter.consume("three", 1_000)).toEqual({ allowed: true });
  });

  it("keys an account independently of password material", () => {
    const first = loginRateLimitKey({
      password: "first secret",
      tenant_slug: " Beepump ",
      username: " Owner ",
    });
    const second = loginRateLimitKey({
      password: "different secret",
      tenant_slug: "beepump",
      username: "owner",
    });

    expect(first).toBe(second);
    expect(first).not.toContain("secret");
  });
});
