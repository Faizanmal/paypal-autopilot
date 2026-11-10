"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";

export function LogoutButton() {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  return (
    <Button
      type="button"
      variant="outline"
      disabled={pending}
      onClick={async () => {
        setPending(true);
        try {
          await api<void>("/api/v1/auth/logout", { method: "POST" });
          router.push("/login");
          router.refresh();
        } finally {
          setPending(false);
        }
      }}
    >
      Sign out
    </Button>
  );
}
