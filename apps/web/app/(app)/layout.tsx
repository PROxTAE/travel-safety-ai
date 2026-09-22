import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { auth } from "@/lib/auth";
import { Profile } from "@/features/auth/profile";

export const dynamic = "force-dynamic";

export default async function ApplicationLayout({ children }: Readonly<{ children: ReactNode }>) {
  const session = process.env.AUTH_SECRET ? await auth() : null;
  return <AppShell profile={session ? <Profile /> : undefined}>{children}</AppShell>;
}
