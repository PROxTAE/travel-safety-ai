import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "@/components/shell/app-shell";

const pathname = vi.fn(() => "/dashboard");

vi.mock("next/navigation", () => ({ usePathname: () => pathname() }));

describe("AppShell", () => {
  beforeEach(() => pathname.mockReturnValue("/dashboard"));

  it("provides keyboard-accessible links to every primary route", () => {
    render(
      <AppShell>
        <p>Content</p>
      </AppShell>,
    );

    expect(screen.getAllByRole("link", { name: "Safety Map" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Emergency" }).length).toBeGreaterThan(0);
    expect(screen.getByText("Content")).toBeInTheDocument();
  });
});
