"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "Home", key: "home" },
  { href: "/projects", label: "Projects", key: "projects" },
  { href: "/create", label: "Create", key: "create", prominent: true },
  { href: "/credits", label: "Credits", key: "credits" },
  { href: "/settings", label: "Settings", key: "settings" },
];

export function BottomNav() {
  const path = usePathname();
  return (
    <nav className="nav" aria-label="Primary">
      <div className="nav-inner">
        {items.map((item) => {
          const on =
            item.href === "/"
              ? path === "/"
              : path === item.href || path.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.key}
              href={item.href}
              className={`${on ? "on" : ""} ${item.prominent ? "create" : ""}`}
            >
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
