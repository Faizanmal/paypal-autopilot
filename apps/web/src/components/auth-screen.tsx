import { ThemeToggle } from "@/components/theme-toggle";

export function AuthScreen({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-3 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:shadow"
      >
        Skip to content
      </a>
      <header className="flex items-center justify-between px-6 py-4">
        <p className="text-sm font-semibold tracking-tight">PayPal Autopilot</p>
        <ThemeToggle />
      </header>
      <main
        id="content"
        className="mx-auto flex w-full max-w-md flex-1 flex-col justify-start gap-6 px-6 py-6 sm:justify-center sm:py-10"
      >
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{description}</p>
        </div>
        {children}
      </main>
    </div>
  );
}
