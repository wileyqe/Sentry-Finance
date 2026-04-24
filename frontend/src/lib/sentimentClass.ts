/**
 * Map a "good"/"bad"/"neutral" sentiment to the matching color CSS class.
 * Single source so the same colors apply across every sparkline + trend
 * label on the Account Details and Manual Asset Details panels.
 */

export type Sentiment = "good" | "bad" | "neutral";

export function sentimentStrokeClass(sentiment: Sentiment): string {
  if (sentiment === "good") return "stroke-[var(--color-gain)]";
  if (sentiment === "bad") return "stroke-[var(--color-loss)]";
  return "stroke-muted-foreground";
}

export function sentimentTextClass(sentiment: Sentiment): string {
  if (sentiment === "good") return "text-[var(--color-gain)]";
  if (sentiment === "bad") return "text-[var(--color-loss)]";
  return "text-muted-foreground";
}
