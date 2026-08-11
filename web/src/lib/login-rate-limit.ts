import { createHash } from "node:crypto";

type RateLimitEntry = {
  count: number;
  windowStartedAt: number;
};

type RateLimitResult =
  | { allowed: true }
  | { allowed: false; retryAfterSeconds: number };

export class FixedWindowRateLimiter {
  private readonly entries = new Map<string, RateLimitEntry>();
  private nextSweepAt = 0;

  constructor(
    private readonly options: {
      limit: number;
      windowMs: number;
      maxTrackedKeys?: number;
    },
  ) {}

  consume(key: string, now = Date.now()): RateLimitResult {
    let entry = this.entries.get(key);
    if (entry && now - entry.windowStartedAt >= this.options.windowMs) {
      this.entries.delete(key);
      entry = undefined;
    }

    if (!entry) {
      if (now >= this.nextSweepAt) {
        this.removeExpired(now);
        this.nextSweepAt = now + Math.min(this.options.windowMs, 60_000);
      }
      if (this.entries.size >= (this.options.maxTrackedKeys ?? 10_000)) {
        return {
          allowed: false,
          retryAfterSeconds: Math.ceil(this.options.windowMs / 1_000),
        };
      }
      this.entries.set(key, { count: 1, windowStartedAt: now });
      return { allowed: true };
    }

    if (entry.count >= this.options.limit) {
      return {
        allowed: false,
        retryAfterSeconds: Math.max(
          1,
          Math.ceil((entry.windowStartedAt + this.options.windowMs - now) / 1_000),
        ),
      };
    }

    entry.count += 1;
    return { allowed: true };
  }

  refund(key: string) {
    const entry = this.entries.get(key);
    if (!entry) return;
    if (entry.count <= 1) this.entries.delete(key);
    else entry.count -= 1;
  }

  clear(key: string) {
    this.entries.delete(key);
  }

  reset() {
    this.entries.clear();
    this.nextSweepAt = 0;
  }

  private removeExpired(now: number) {
    for (const [key, entry] of this.entries) {
      if (now - entry.windowStartedAt >= this.options.windowMs) {
        this.entries.delete(key);
      }
    }
  }
}

const loginLimiter = new FixedWindowRateLimiter({
  limit: 10,
  windowMs: 15 * 60 * 1_000,
});

export function loginRateLimitKey(payload: Record<string, unknown>) {
  const tenant = typeof payload.tenant_slug === "string" ? payload.tenant_slug.trim().toLowerCase() : "";
  const username = typeof payload.username === "string" ? payload.username.trim().toLowerCase() : "";
  return createHash("sha256")
    .update(tenant)
    .update("\0")
    .update(username)
    .digest("hex");
}

export function consumeLoginAttempt(key: string) {
  return loginLimiter.consume(key);
}

export function refundLoginAttempt(key: string) {
  loginLimiter.refund(key);
}

export function clearLoginAttempts(key: string) {
  loginLimiter.clear(key);
}

export function resetLoginRateLimiterForTests() {
  loginLimiter.reset();
}
