"use client";

import { MoonIcon, SunIcon } from "@phosphor-icons/react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";

export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const nextTheme = isDark ? "light" : "dark";
  const label = isDark ? "切换为浅色主题" : "切换为深色主题";

  return (
    <Button
      aria-label={label}
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
