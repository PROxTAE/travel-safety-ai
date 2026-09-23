"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { navigationItems } from "./navigation";
import { ConnectionStatus } from "@/components/ui/connection-status";

function isActive(pathname: string, href: string) {
  return href === "/dashboard" ? pathname === href : pathname.startsWith(href.replace("/new", ""));
}

export function AppShell({
  children,
  profile,
}: Readonly<{ children: ReactNode; profile?: ReactNode }>) {
  const pathname = usePathname();

  return (
    <div className="shell-grid">
      <aside className="app-sidebar" aria-label="Primary navigation">
        <Link className="sidebar-brand" href="/dashboard" aria-label="Smart Travel Assistant home">
          <Image src="/assets/branding/app-logo-mark.png" width={76} height={76} alt="" priority />
          <span className="sr-only">Smart Travel Assistant</span>
        </Link>
        <nav>
          <ul className="nav-list">
            {navigationItems.map((item) => (
              <li key={item.href}>
                <Link
                  className="nav-link"
                  href={item.href}
                  data-active={isActive(pathname, item.href)}
                  aria-label={item.enLabel}
                >
                  <span className="nav-icon" aria-hidden="true">
                    <Image src={item.icon} width={34} height={34} alt="" />
                  </span>
                  <span className="nav-label">{item.label}</span>
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <p className="sidebar-tagline" aria-hidden="true">
          เดินทางปลอดภัย
          <br />
          ไปได้ไกลกว่า
        </p>
      </aside>
      <main className="app-main">
        <header className="app-header">
          <Link className="header-brand" href="/dashboard" aria-label="Smart Travel Assistant home">
            <Image
              src="/assets/branding/logo-horizontal.png"
              width={360}
              height={120}
              alt="Smart Travel Assistant"
              priority
            />
          </Link>
          <div className="profile-summary" aria-label="Profile summary">
            <span className="header-sun" aria-hidden="true">
              ☀
            </span>
            <span className="profile-copy">
              {profile || (
                <>
                  <strong>สวัสดี, นักเดินทาง!</strong>
                  <br />
                  ท่องเที่ยวปลอดภัย มั่นใจทุกเส้นทาง
                </>
              )}
            </span>
            <span className="profile-avatar desktop-profile-avatar">
              <Image
                src="/assets/branding/app-logo-mark.png"
                width={42}
                height={42}
                alt="Guest profile"
              />
            </span>
            <details className="mobile-navigation" open>
              <summary
                className="profile-avatar mobile-nav-toggle"
                aria-controls="mobile-primary-navigation"
                aria-label="Toggle primary navigation"
              >
                <Image src="/assets/branding/app-logo-mark.png" width={42} height={42} alt="" />
              </summary>
              <nav
                id="mobile-primary-navigation"
                className="mobile-nav"
                aria-label="Primary navigation"
              >
                {navigationItems.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    data-active={isActive(pathname, item.href)}
                    aria-label={item.enLabel}
                  >
                    <Image src={item.icon} width={30} height={30} alt="" aria-hidden="true" />
                    <span className="mobile-nav-label">{item.label}</span>
                  </Link>
                ))}
              </nav>
            </details>
          </div>
        </header>
        <div className="content-frame">
          <ConnectionStatus />
          {children}
        </div>
      </main>
    </div>
  );
}
