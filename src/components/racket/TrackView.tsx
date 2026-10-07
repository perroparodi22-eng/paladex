"use client";
import { useEffect } from "react";
import { track } from "@/lib/analytics";

/** Records one racket_viewed event per page view (feeds "Most popular"). */
export function TrackView({ slug }: { slug: string }) {
  useEffect(() => {
    track("racket_viewed", { slug });
  }, [slug]);
  return null;
}
