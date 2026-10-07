/**
 * Affiliate redirect. Logs the click (no personal data), then:
 *  - redirects to the affiliate URL when it is real, https and on one of the
 *    retailer's allow-listed domains (no open redirects), or
 *  - sends the visitor to an explanation page when the link is a placeholder,
 *    unsafe or inactive. Nothing pretends a placeholder link works.
 */
import { NextResponse } from "next/server";
import { recordClick, resolveOffer } from "@/server/repositories/affiliate";
import { recordEvent } from "@/server/repositories/events";

export const dynamic = "force-dynamic";

export async function GET(req: Request, ctx: { params: Promise<{ offerId: string }> }) {
  const { offerId } = await ctx.params;
  const id = Number(offerId);
  const base = new URL(req.url);
  if (!Number.isInteger(id) || id <= 0) return NextResponse.redirect(new URL("/link-unavailable?reason=missing", base), 303);

  const target = await resolveOffer(id);
  if (!target) return NextResponse.redirect(new URL("/link-unavailable?reason=missing", base), 303);

  let sourcePath: string | null = null;
  const ref = req.headers.get("referer");
  if (ref) {
    try {
      const u = new URL(ref);
      if (u.host === base.host) sourcePath = u.pathname;
    } catch {
      // ignore malformed referers
    }
  }

  try {
    await recordClick(target, sourcePath);
    await recordEvent("affiliate_clicked", { slug: target.productSlug, retailer: target.retailerName, value: target.reason }, sourcePath);
  } catch {
    // Logging must never block the visitor.
  }

  if (target.reason === "ok" && target.destination) {
    const res = NextResponse.redirect(target.destination, 302);
    res.headers.set("Cache-Control", "no-store");
    res.headers.set("X-Robots-Tag", "noindex, nofollow");
    return res;
  }
  const params = new URLSearchParams({ reason: target.reason, retailer: target.retailerName, racket: target.productSlug, name: target.productName });
  return NextResponse.redirect(new URL(`/link-unavailable?${params}`, base), 303);
}
