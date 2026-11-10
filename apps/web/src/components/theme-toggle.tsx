"use client";

import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";

function subscribe(onStoreChange: () => void) {
  window.addEventListener("storage", onStoreChange);
  return () => window.removeEventListener("storage", onStoreChange);
}

function readTheme(): "light" | "dark" {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

function clientReady() {
  return true;
}

export function ThemeToggle() {
  // Defer theme-dependent label until after hydration so the inline dark-mode
  // boot script cannot disagree with the server snapshot.
  const ready = useSyncExternalStore(subscribe, clientReady, () => false);
  const theme = useSyncExternalStore(subscribe, readTheme, () => "light" as const);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    localStorage.setItem("theme", next);
    window.dispatchEvent(new Event("storage"));
  }

  const label = !ready ? "Theme" : theme === "dark" ? "Light mode" : "Dark mode";

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={toggle}
      aria-pressed={ready ? theme === "dark" : undefined}
      suppressHydrationWarning
    >
      {label}
    </Button>
  );
}
