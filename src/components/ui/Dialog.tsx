"use client";
/**
 * Native <dialog> wrapper: real modal focus handling, Escape to close,
 * backdrop click to close. `sheet` docks to the bottom on phones, `drawer`
 * slides in from the left edge (the site menu). `bare` drops the title bar
 * for panels that draw their own. Opening and closing animate;
 * reduced motion makes both instant.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";
import { Icon } from "./Icon";

const CLOSE_MS = 320;

export function Dialog({
  open,
  onClose,
  title,
  children,
  variant = "center",
  className,
  hideTitle = false,
  bare = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  variant?: "center" | "sheet" | "full" | "drawer";
  className?: string;
  hideTitle?: boolean;
  /** No built-in title bar; the content provides its own heading and close button. */
  bare?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [mounted, setMounted] = useState(open);
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open) {
      setMounted(true);
      setClosing(false);
      if (!d.open) d.showModal();
      document.documentElement.style.overflow = "hidden";
      return;
    }
    if (d.open) {
      const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      setClosing(true);
      const t = window.setTimeout(
        () => {
          d.close();
          setClosing(false);
          setMounted(false);
          document.documentElement.style.overflow = "";
        },
        reduce ? 0 : CLOSE_MS,
      );
      return () => window.clearTimeout(t);
    }
  }, [open]);

  useEffect(
    () => () => {
      document.documentElement.style.overflow = "";
    },
    [],
  );

  return (
    <dialog
      ref={ref}
      aria-label={title}
      data-closing={closing || undefined}
      onClose={() => open && onClose()}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
      className={cn(
        "dialog m-0 max-h-none max-w-none bg-transparent p-0 text-ink",
        variant === "center" && "fixed inset-0 m-auto h-fit w-[min(92vw,720px)]",
        variant === "sheet" && "fixed inset-x-0 bottom-0 top-auto w-full sm:inset-0 sm:m-auto sm:h-fit sm:w-[min(92vw,560px)]",
        variant === "full" && "fixed inset-0 h-dvh w-screen",
        variant === "drawer" && "dialog-drawer fixed inset-y-0 left-0 right-auto h-dvh w-[min(440px,90vw)]",
        className,
      )}
    >
      {mounted && (
        <div
          className={cn(
            "relative flex max-h-[92dvh] flex-col overflow-hidden border border-white/8 bg-surface shadow-lift",
            variant === "center" && "rounded-[22px]",
            variant === "sheet" && "rounded-t-[22px] sm:rounded-[22px]",
            variant === "full" && "h-full max-h-none rounded-none",
            variant === "drawer" && "h-full max-h-none rounded-r-[28px] border-l-0",
          )}
        >
          {!bare && (
            <div className={cn("flex items-center justify-between gap-4 px-5 py-3", variant !== "drawer" && "border-b border-white/8", hideTitle && "sr-only")}>
              <h2 className="text-sm font-semibold text-ink">{title}</h2>
              <button type="button" onClick={onClose} className="btn btn-ghost btn-icon -mr-2" aria-label="Close">
                <Icon name="close" />
              </button>
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </div>
      )}
    </dialog>
  );
}
