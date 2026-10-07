/**
 * Product poster: the real product photo when one exists, otherwise the
 * generated illustration. Local images go through next/image; external
 * images (from an asset CDN) render as plain <img> so a missing remote
 * pattern never breaks the page.
 */
import Image from "next/image";
import type { RacketShape, RacketVisual } from "@/domain/types";
import { RacketIllustration } from "./RacketIllustration";
import { cn } from "@/lib/cn";

export interface PosterRacket {
  shape: RacketShape;
  visual: RacketVisual;
  imageUrl: string | null;
  imageAlt: string;
  fullName: string;
}

export function RacketPoster({
  racket,
  sizes = "(max-width: 768px) 60vw, 360px",
  priority = false,
  className,
  imgClassName,
}: {
  racket: PosterRacket;
  sizes?: string;
  priority?: boolean;
  className?: string;
  imgClassName?: string;
}) {
  if (racket.imageUrl) {
    const local = racket.imageUrl.startsWith("/");
    return (
      <div className={cn("relative h-full w-full", className)}>
        {local ? (
          <Image
            src={racket.imageUrl}
            alt={racket.imageAlt}
            fill
            sizes={sizes}
            priority={priority}
            className={cn("object-contain", imgClassName)}
          />
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={racket.imageUrl} alt={racket.imageAlt} className={cn("absolute inset-0 h-full w-full object-contain", imgClassName)} loading={priority ? "eager" : "lazy"} />
        )}
      </div>
    );
  }
  return (
    <div className={cn("relative flex h-full w-full items-center justify-center", className)}>
      <RacketIllustration
        shape={racket.shape}
        visual={racket.visual}
        title={`Illustration of the ${racket.fullName} (${racket.shape} shape)`}
        className={cn("h-full w-auto max-w-full", imgClassName)}
      />
    </div>
  );
}
