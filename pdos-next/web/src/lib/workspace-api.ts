export type WorkspaceTransport = <T>(path: string, body?: unknown) => Promise<T>;
export type ReadRequestCode = "READ_SUPERSEDED" | "READ_CANCELLED" | "READ_SCOPE_DISPOSED";

export class WorkspaceReadError extends Error {
  readonly code: ReadRequestCode;
  constructor(code: ReadRequestCode) {
    super(code === "READ_SCOPE_DISPOSED" ? "当前页面范围已切换，请在新的范围读取。" : code === "READ_CANCELLED" ? "本次排队读取已取消，请按当前范围刷新。" : "当前读取早于本次操作或范围变化，请刷新当前事实。");
    this.name = "WorkspaceReadError";
    this.code = code;
  }
}

type ReadEntry = {
  path: string;
  epoch: number;
  started: boolean;
  cancelled: boolean;
  promise: Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (error: unknown) => void;
};

/** Page-owned in-flight coordination. Resolved data is never retained or cached. */
export function createWorkspaceApi(transport: WorkspaceTransport, scope: string, maxReads = 2) {
  if (!scope || !Number.isSafeInteger(maxReads) || maxReads < 1) throw new Error("需要明确页面范围与有效读取上限。");
  let epoch = 0, activeReads = 0, activePosts = 0, disposed = false;
  let queue: ReadEntry[] = [];
  const entries = new Map<string, ReadEntry>();
  const key = (entry: Pick<ReadEntry, "path" | "epoch">) => `${entry.epoch}\u0000${entry.path}`;

  function remove(entry: ReadEntry) {
    if (entries.get(key(entry)) === entry) entries.delete(key(entry));
  }
  function cancel(entry: ReadEntry, code: ReadRequestCode) {
    if (entry.cancelled) return;
    entry.cancelled = true;
    remove(entry);
    entry.reject(new WorkspaceReadError(code));
  }
  function advance(preserveQueued: boolean, code: ReadRequestCode = "READ_SUPERSEDED") {
    epoch++;
    for (const entry of [...entries.values()]) {
      if (preserveQueued && !entry.started && !entry.cancelled) {
        remove(entry);
        entry.epoch = epoch;
        entries.set(key(entry), entry);
      } else cancel(entry, code);
    }
    queue = queue.filter(entry => !entry.cancelled);
  }
  function drain() {
    if (disposed || activePosts > 0) return;
    while (activeReads < maxReads && queue.length) {
      const entry = queue.shift()!;
      if (entry.cancelled) continue;
      if (entry.epoch !== epoch) { cancel(entry, "READ_SUPERSEDED"); continue; }
      entry.started = true;
      activeReads++;
      void Promise.resolve().then(() => {
        // A mutation can invalidate a scheduled read before its transport starts.
        if (entry.cancelled || disposed || entry.epoch !== epoch) return undefined;
        return transport<unknown>(entry.path);
      }).then(value => {
        if (entry.cancelled) return;
        if (disposed || entry.epoch !== epoch) cancel(entry, disposed ? "READ_SCOPE_DISPOSED" : "READ_SUPERSEDED");
        else { remove(entry); entry.resolve(value); }
      }, failure => { if (!entry.cancelled) { remove(entry); entry.reject(failure); } }).finally(() => {
        remove(entry);
        activeReads--;
        drain();
      });
    }
  }
  const api: WorkspaceTransport = <T>(path: string, body?: unknown): Promise<T> => {
    if (disposed) return Promise.reject(new WorkspaceReadError("READ_SCOPE_DISPOSED"));
    if (body !== undefined) {
      // POSTs are never coalesced, queued behind reads, or automatically retried.
      advance(false);
      activePosts++;
      return Promise.resolve().then(() => transport<T>(path, body)).finally(() => {
        activePosts--;
        // Reads requested during the POST run only after the final current epoch.
        advance(true);
        drain();
      });
    }
    const identity = `${epoch}\u0000${path}`, existing = entries.get(identity);
    if (existing) return existing.promise as Promise<T>;
    let resolve!: ReadEntry["resolve"], reject!: ReadEntry["reject"];
    const promise = new Promise<unknown>((done, fail) => { resolve = done; reject = fail; });
    const entry: ReadEntry = { path, epoch, promise, resolve, reject, started: false, cancelled: false };
    entries.set(identity, entry);
    queue.push(entry);
    drain();
    return promise as Promise<T>;
  };
  return {
    scope,
    api,
    cancelRead(path: string) { for (const entry of [...entries.values()]) if (entry.path === path) cancel(entry, "READ_CANCELLED"); queue = queue.filter(entry => !entry.cancelled); drain(); },
    dispose() { if (disposed) return; disposed = true; advance(false, "READ_SCOPE_DISPOSED"); queue = []; },
    // React replays effect setup/cleanup in development. Revival starts a new
    // empty epoch, never revives any disposed promises or another scope.
    activate() { if (disposed) { disposed = false; epoch++; drain(); } },
  };
}
