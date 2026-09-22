import { getToken } from "next-auth/jwt";
import { NextResponse, type NextRequest } from "next/server";
import { sessionCookie } from "@/lib/auth/session";

export async function proxy(request: NextRequest) {
  const token = process.env.AUTH_SECRET
    ? await getToken({
        req: request,
        secret: process.env.AUTH_SECRET,
        cookieName: sessionCookie,
        salt: sessionCookie,
      })
    : null;
  if (!token || token.error || !token.accessToken) {
    const login = new URL("/login", request.url);
    login.searchParams.set("callbackUrl", request.nextUrl.pathname + request.nextUrl.search);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/trips/:path*", "/safety-map/:path*", "/assistant/:path*"],
};
