"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const items = [
  { href: "/", label: "Home", key: "home" },
  { href: "/friends", label: "Friends", key: "friends" },
  { href: "/create/friend-group", label: "Create", key: "create", prominent: true },
  { href: "/projects", label: "Videos", key: "projects" },
  { href: "/profile", label: "Profile", key: "profile" },
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
