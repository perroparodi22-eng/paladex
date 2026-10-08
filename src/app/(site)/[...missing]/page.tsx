import { notFound } from "next/navigation";

/**
 * Sends URLs that match no route to (site)/not-found.tsx, so a stray link
 * still gets the header, footer and search. Without it Next falls back to
 * the bare app/not-found.tsx. Every real route is more specific and wins.
 */
export default function Missing() {
  notFound();
}
