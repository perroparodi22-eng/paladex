"use client";
/** "Show on model": moves the page's 3D viewer to the part a row describes. */
import { useViewerBridge, type ViewerAction } from "@/components/three/ViewerBridge";
import { Icon } from "@/components/ui/Icon";
import { track } from "@/lib/analytics";
import { cn } from "@/lib/cn";

export function ShowOnModel({ action, label = "Show on model", className, specKey }: { action: ViewerAction; label?: string; className?: string; specKey?: string }) {
  const bridge = useViewerBridge();
  if (!bridge) return null;
  return (
    <button
      type="button"
      onClick={() => {
        bridge.act(action);
        track("annotation_opened", { source: "spec-row", key: specKey ?? action.view ?? "spec" });
      }}
      className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-xl px-2 py-1 text-xs font-semibold text-court hover:bg-court/10", className)}
    >
      <Icon name="cube" size={14} /> {label}
    </button>
  );
}
