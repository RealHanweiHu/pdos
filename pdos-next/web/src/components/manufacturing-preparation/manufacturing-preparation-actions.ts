import {
  mpInputs, mpPrepared, mpReceipt, validMpCommand,
  type MpApi, type MpPending, type MpPrepared, type MpReceipt,
} from "./manufacturing-preparation-contract";

export type MpRequestResult = { stage: "preview"; prepared: MpPrepared } | { stage: "saved"; receipt: MpReceipt };

/** Actual port sequence. Only an explicitly persisted execute request reaches the write port. */
export async function runMpRequest(
  api: MpApi,
  productId: string,
  principalId: string,
  waiting: MpPending,
  onStage: (next: MpPending) => void,
  isActive: () => boolean,
): Promise<MpRequestResult | null> {
  if (!["inputs", "preview", "execute"].includes(waiting.stage) || !validMpCommand(waiting.command) || waiting.command.product_id !== productId || (waiting.stage !== "execute" && waiting.command.payload.confirmation_token !== undefined) || (waiting.stage === "execute" && !waiting.command.payload.confirmation_token)) throw new Error("原命令阶段或固定型号不一致，不能继续办理。");
  if (!isActive()) return null;
  let stage = waiting;
  if (stage.stage === "inputs") {
    const value = await api<unknown>(`v1/products/${productId}/manufacturing-preparations/inputs`, stage.command);
    if (!isActive()) return null;
    const returned = mpInputs(value, stage.command, principalId);
    if (!returned) throw new Error("服务器未返回与原语义、本人和固定范围一致的完整核对。");
    stage = { stage: "preview", command: returned };
    onStage(stage);
  }
  if (stage.stage === "preview") {
    if (!isActive()) return null;
    const value = await api<unknown>("v1/commands/preview", stage.command);
    if (!isActive()) return null;
    const prepared = mpPrepared(value, stage.command, principalId);
    if (!prepared) throw new Error("尚未取得与原请求一致且未过期的完整服务器实质预览。");
    return { stage: "preview", prepared };
  }
  // An UNKNOWN retry must carry its original key, material and token even after preview expiry.
  // The server checks current scope, sources and qualification before returning the original receipt.
  const receipt = await api<unknown>("v1/commands", stage.command);
  const expectedRevision = (stage.command.payload.expected_previous_revision ?? 0) + 1;
  if (!mpReceipt(receipt, stage.command.operation) || receipt.subject_revision !== expectedRevision) throw new Error("尚未取得本操作及固定续版的明确保存回执，请保留原请求核对。");
  return { stage: "saved", receipt };
}
