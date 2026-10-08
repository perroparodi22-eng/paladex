"use client";
/**
 * Small disclosure popover: a button toggles a panel; Escape, outside click
 * and focus leaving the panel close it. Used for viewer menus and sorting.
 */
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Popover({
  trigger,
  triggerClassName,
  label,
  children,
  align = "start",
  side = "bottom",
  className,
  panelClassName,
}: {
  trigger: (open: boolean) => ReactNode;
  triggerClassName?: string;
  label: string;
  children: (close: () => void) => ReactNode;
  align?: "start" | "end" | "center";
  side?: "top" | "bottom";
  className?: string;
  panelClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        setOpen(false);
        button.current?.focus();
      }
    };
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  return (
    <div ref={root} className={cn("relative", className)}>
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        aria-label={label}
        title={label}
        onClick={() => setOpen((o) => !o)}
        className={triggerClassName}
        data-active={open || undefined}
      >
        {trigger(open)}
      </button>
      {open && (
        <div
          id={id}
          role="group"
          aria-label={label}
          className={cn(
            "glass absolute z-50 min-w-56 p-2 shadow-2xl",
            side === "top" ? "bottom-full mb-2" : "top-full mt-2",
            align === "end" ? "right-0" : align === "center" ? "left-1/2 -translate-x-1/2" : "left-0",
            "bg-surface/95",
            panelClassName,
          )}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node) && !root.current?.contains(e.relatedTarget as Node)) setOpen(false);
          }}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}
