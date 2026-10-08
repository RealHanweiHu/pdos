/** Opens the existing personal assistant with its current page context. */
export type PreprojectLaunch = { goal: "category" | "proposal" };
export function openXiaopai(intent?: PreprojectLaunch) {
  window.dispatchEvent(new CustomEvent("pdos:open-xiaopai", { detail: intent }));
}
