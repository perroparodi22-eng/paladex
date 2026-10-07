"use client";
import Link from "next/link";
import { useEffect } from "react";
import { Container } from "@/components/layout/Section";

export default function SiteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <Container className="py-24">
      <div className="plate mx-auto max-w-xl p-8 text-center">
        <h1 className="display text-5xl">Something went wrong</h1>
        <p className="mt-4 text-ink-2">
          We couldn&apos;t load this page. It may be a temporary problem with our database. Try again in a moment.
          {error.digest && <span className="mt-2 block text-xs text-ink-3">Reference: {error.digest}</span>}
        </p>
        <div className="mt-6 flex justify-center gap-2">
          <button type="button" className="btn btn-primary" onClick={reset}>
            Try again
          </button>
          <Link href="/" className="btn btn-secondary">
            Home
          </Link>
        </div>
      </div>
    </Container>
  );
}
