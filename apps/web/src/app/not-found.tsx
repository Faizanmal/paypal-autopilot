import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex w-full max-w-lg flex-1 flex-col justify-center gap-3 px-6 py-16">
      <h1 className="text-2xl font-semibold">Page not found</h1>
      <p className="text-sm text-muted-foreground">That route is not part of PayPal Autopilot.</p>
      <Link href="/" className="text-sm underline">
        Back home
      </Link>
    </main>
  );
}
