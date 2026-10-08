"use client";

import { useSyncExternalStore } from "react";

const key = "pdos.navigation.collapsed";
const changeEvent = "pdos:navigation-preference";
let memoryCollapsed = false;
let sessionFallback = false;

function readCollapsed() {
  if (sessionFallback) return memoryCollapsed;
  try { return window.localStorage.getItem(key) === "true"; }
  catch { return memoryCollapsed; }
}

function subscribe(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(changeEvent, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(changeEvent, listener);
  };
}

export function useCollapsedNavigation() {
  const collapsed = useSyncExternalStore(subscribe, readCollapsed, () => false);
  const toggle = () => {
    memoryCollapsed = !collapsed;
    try { window.localStorage.setItem(key, String(!collapsed)); sessionFallback = false; }
    catch { sessionFallback = true; }
    window.dispatchEvent(new Event(changeEvent));
  };
  return [collapsed, toggle] as const;
}
