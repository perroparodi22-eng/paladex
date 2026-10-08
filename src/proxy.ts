/**
 * Proxy (Next 16's successor to middleware): fast redirect away from /admin
 * for visitors without a valid session. Pages and server actions verify the
 * session again on the server; this is only the first gate.
 */
import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE, verifySessionToken } from "@/server/auth/session";

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (pathname.startsWith("/admin") && !pathname.startsWith("/admin/login")) {
    if (!verifySessionToken(request.cookies.get(SESSION_COOKIE)?.value)) {
      const url = request.nextUrl.clone();
      url.pathname = "/admin/login";
      url.search = "";
      return NextResponse.redirect(url);
    }
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/admin/:path*"],
};
