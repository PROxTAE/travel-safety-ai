import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";

export default function ApplicationLayout({ children }: Readonly<{ children: ReactNode }>) {
  return <AppShell>{children}</AppShell>;
}
