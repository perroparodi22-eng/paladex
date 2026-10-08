import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Logo } from "@/components/layout/Logo";
import { LoginForm } from "@/components/admin/LoginForm";
import { isAdmin } from "@/server/auth/guard";
import { adminConfigured } from "@/server/auth/session";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage() {
  if (await isAdmin()) redirect("/admin");
  const configured = adminConfigured();
  return (
    <main className="stage-sky grid min-h-dvh place-items-center px-4 py-16">
      <div className="plate w-full max-w-sm p-6 sm:p-8">
        <Logo />
        <h1 className="display mt-8 text-4xl mb-6">Admin sign in</h1>
        {configured ? (
          <LoginForm />
        ) : (
          <div className="space-y-3 text-sm leading-relaxed text-ink-2">
            <p className="text-ink">The admin is not configured on this server yet.</p>
            <p>
              Set <code className="num text-ink">ADMIN_PASSWORD_HASH</code> and <code className="num text-ink">ADMIN_SESSION_SECRET</code> (at least 32
              characters). Locally, <code className="num text-ink">npm run setup</code> creates both. To make a hash for a new password, run{" "}
              <code className="num text-ink">npm run admin:hash</code>.
            </p>
          </div>
        )}
      </div>
    </main>
  );
}
