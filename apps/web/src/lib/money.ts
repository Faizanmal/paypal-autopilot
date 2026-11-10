const CLOSED = new Set([
  "paid",
  "marked_as_paid",
  "cancelled",
  "refunded",
  "partially_refunded",
  "marked_as_refunded",
]);

export function toCents(amount: string): number {
  const negative = amount.trim().startsWith("-");
  const [whole, fraction = ""] = amount.trim().replace("-", "").split(".");
  const cents = Number(whole || "0") * 100 + Number((fraction + "00").slice(0, 2));
  return negative ? -cents : cents;
}

export function fromCents(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const absolute = Math.abs(cents);
  return `${sign}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, "0")}`;
}

export function sumAmounts(amounts: string[]): string {
  return fromCents(amounts.reduce((total, amount) => total + toCents(amount), 0));
}

export function money(currency: string, amount: string): string {
  return `${currency} ${amount}`;
}

export function isClosedInvoice(status: string): boolean {
  return CLOSED.has(status);
}

export function isOverdue(status: string, dueAt: string | null, now = Date.now()): boolean {
  if (!dueAt || isClosedInvoice(status) || status === "draft") {
    return false;
  }
  return new Date(dueAt).getTime() < now;
}
