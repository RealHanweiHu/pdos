/** Opens the existing personal assistant with its current page context. */
export function openXiaopai() {
  window.dispatchEvent(new Event("pdos:open-xiaopai"));
}
