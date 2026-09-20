"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { navigationItems } from "./navigation";

function isActive(pathname: string, href: string) {
  return href === "/dashboard" ? pathname === href : pathname.startsWith(href.replace("/new", ""));
}

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  const pathname = usePathname();

  return (
    <div className="shell-grid">
      <aside className="app-sidebar" aria-label="Primary navigation">
        <Link className="brand" href="/dashboard" aria-label="Smart Travel Assistant home">
          <span className="brand-mark" aria-hidden="true">
            ✦
          </span>
          <span className="nav-label">Smart Travel</span>
        </Link>
        <nav>
          <ul className="nav-list">
            {navigationItems.map((item) => (
              <li key={item.href}>
                <Link
                  className="nav-link"
                  href={item.href}
                  data-active={isActive(pathname, item.href)}
                >
                  <span className="nav-icon" aria-hidden="true">
                    {item.icon}
                  </span>
                  <span className="nav-label">{item.label}</span>
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <main className="app-main">
        <header className="app-header">
          <Link className="brand" href="/dashboard">
            <span className="brand-mark" aria-hidden="true">
              ✦
            </span>
            <span>Smart Travel Assistant</span>
          </Link>
          <div className="profile-summary" aria-label="Profile summary">
            <span className="profile-copy">
              <strong>Hello, traveler</strong>
              <br />
              Sign in to personalize
            </span>
            <span className="profile-avatar" aria-hidden="true">
              🙂
            </span>
          </div>
        </header>
        <div className="data-status" role="status">
          Live travel data will appear here when you are signed in.
        </div>
        {children}
      </main>
      <nav className="mobile-nav" aria-label="Primary navigation">
        {navigationItems.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            data-active={isActive(pathname, item.href)}
            aria-label={item.label}
          >
            <span aria-hidden="true">{item.icon}</span>
          </Link>
        ))}
      </nav>
    </div>
  );
}
