"use client";

import { MoonIcon, SunIcon } from "@phosphor-icons/react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";

const subscribe = () => () => undefined;

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const isDark = mounted && resolvedTheme === "dark";
  const nextTheme = isDark ? "light" : "dark";
  const label = mounted
    ? isDark
      ? "切换为浅色主题"
      : "切换为深色主题"
    : "切换主题";

  return (
    <Button
      aria-label={label}
      className="size-11 sm:size-8"
      disabled={!mounted}
      onClick={() => setTheme(nextTheme)}
      size="icon"
      title={label}
      variant="ghost"
    >
      {isDark ? (
        <SunIcon aria-hidden="true" weight="regular" />
      ) : (
        <MoonIcon aria-hidden="true" weight="regular" />
      )}
    </Button>
  );
}
