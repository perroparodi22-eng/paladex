/**
 * Shows where a racket's 3D model comes from. Always visible on the viewer:
 * a placeholder must never pass for the real thing.
 */
import type { ModelStatus } from "@/domain/types";
import { MODEL_STATUS_INFO } from "@/domain/vocab";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

export function ProvenanceBadge({ status, className, long = false }: { status: ModelStatus; className?: string; long?: boolean }) {
  const info = MODEL_STATUS_INFO[status];
  const tone =
    status === "official" || status === "licensed"
      ? "bg-ok/15 text-ok"
      : status === "platform"
        ? "bg-court text-on-court"
        : status === "placeholder"
          ? "badge-warn"
          : "bg-surface-2 text-ink-2";
  return (
    <span className={cn("badge whitespace-nowrap", tone, className)} title={info.description}>
      <Icon name={status === "unavailable" ? "image" : "cube"} size={12} />
      {long ? info.label : info.badge}
    </span>
  );
}
