import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThemeToggle } from "./theme-toggle";

const setTheme = vi.fn();
let resolvedTheme = "light";

vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme, setTheme }),
}));

describe("ThemeToggle", () => {
  afterEach(() => {
    setTheme.mockReset();
    resolvedTheme = "light";
  });

  it("switches a light interface to the dark theme", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(
      screen.getByRole("button", { name: "切换为深色主题" }),
    );

    expect(setTheme).toHaveBeenCalledWith("dark");
  });

  it("switches a dark interface to the light theme", async () => {
    resolvedTheme = "dark";
    const user = userEvent.setup();
    render(<ThemeToggle />);

    await user.click(
      screen.getByRole("button", { name: "切换为浅色主题" }),
    );

    expect(setTheme).toHaveBeenCalledWith("light");
  });
});
