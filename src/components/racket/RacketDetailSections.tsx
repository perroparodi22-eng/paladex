/**
 * Sections of the racket page: who it's for, platform scores, review,
 * 3D model provenance and the photo gallery.
 */
import Image from "next/image";
import Link from "next/link";
import type { Racket } from "@/domain/types";
import { LEVEL_INFO, MODEL_STATUS_INFO, SCORE_INFO, SCORE_KEYS, STYLE_INFO, BASIS_INFO } from "@/domain/vocab";
import { ScoreBar } from "./ScoreBar";
import { ShowOnModel } from "./ShowOnModel";
import { ProvenanceBadge } from "./ProvenanceBadge";
import { siteConfig } from "@/config/site";
import { Icon } from "@/components/ui/Icon";
import { formatDate } from "@/lib/format";

export function WhoIsItFor({ racket }: { racket: Racket }) {
  const ev = racket.evaluation;
  if (!ev) return null;
  const shapeLine =
    racket.specs.shape === "diamond"
      ? { text: "The diamond shape is clearest in the front view: the widest point sits up near the tip.", action: { view: "front" as const } }
      : racket.specs.shape === "round"
        ? { text: "The round head is clearest in the front view: the widest point sits in the middle.", action: { view: "front" as const } }
        : { text: "The teardrop/hybrid head widens above the middle. Compare the front view with a round racket.", action: { view: "front" as const } };
  const rows = [
    { label: "Best for", value: ev.bestFor },
    { label: "Playing style", value: racket.styles.map((s) => STYLE_INFO[s].label).join(" / ") || "—" },
    { label: "Level", value: racket.levels.map((l) => LEVEL_INFO[l].label).join(" / ") || "—" },
    { label: "Recommended for", value: ev.recommendedFor },
    { label: "Not ideal for", value: ev.notIdealFor },
  ];
  return (
    <div>
      <dl className="border-t border-ink/10">
        {rows.map((r) => (
          <div key={r.label} className="grid grid-cols-[minmax(0,9rem)_1fr] gap-4 border-b border-ink/10 py-3">
            <dt className="text-sm text-ink-2">{r.label}</dt>
            <dd className={r.label === "Not ideal for" ? "text-ink/80" : "text-ink"}>{r.value}</dd>
          </div>
        ))}
      </dl>
      <div className="mt-4 space-y-2">
        <p className="flex flex-wrap items-center justify-between gap-2 text-sm text-ink-2">
          {shapeLine.text} <ShowOnModel action={shapeLine.action} label="Front view" specKey="who-shape" />
        </p>
        {racket.specs.balance && (
          <p className="flex flex-wrap items-center justify-between gap-2 text-sm text-ink-2">
            The balance point is shown in the edge view with the balance overlay.
            <ShowOnModel action={{ view: "edge", overlays: ["balance"] }} label="Balance overlay" specKey="who-balance" />
          </p>
        )}
      </div>
      <p className="mt-4 text-xs text-ink-3">
        {BASIS_INFO.platform.label}: our interpretation of the specs, not a manufacturer claim.
      </p>
    </div>
  );
}

export function ScoresPanel({ racket }: { racket: Racket }) {
  const ev = racket.evaluation;
  if (!ev) return <p className="text-ink-2">No platform evaluation yet.</p>;
  return (
    <div>
      <div className="flex items-end justify-between gap-4 border-b border-ink/10 pb-4">
        <div>
          <p className="label">Overall platform score</p>
          <p className="num text-5xl font-bold leading-none">
            {ev.overall.toFixed(1)}
            <span className="text-xl font-semibold text-ink-3">/10</span>
          </p>
        </div>
        {ev.isSample && <span className="badge badge-warn ">Sample evaluation</span>}
      </div>
      <div className="mt-4 space-y-2.5">
        {SCORE_KEYS.map((k) => (
          <ScoreBar key={k} label={SCORE_INFO[k].label} value={ev[k]} hint={SCORE_INFO[k].meaning} color={k === "sweetSpot" ? "var(--color-ball)" : undefined} />
        ))}
      </div>
      <p className="mt-4 text-xs leading-relaxed text-ink-3">
        These are {siteConfig.name}&apos;s own evaluation scores (methodology {ev.methodologyVersion}), not manufacturer-certified measurements. Scores are on the same 1–10
        scale across the site.
      </p>
    </div>
  );
}

export function ReviewBlock({ racket }: { racket: Racket }) {
  const r = racket.review;
  if (!r) return null;
  return (
    <article>
      <div className="flex flex-wrap items-center gap-2">
        {r.isSample && <span className="badge badge-warn ">Sample editorial</span>}
        <span className="text-xs text-ink-3">{r.author}</span>
      </div>
      <h3 className="mt-3 title text-3xl leading-none">{r.title}</h3>
      <p className="mt-3 text-[1.0625rem] leading-relaxed text-ink/90">{r.summary}</p>
      <p className="mt-3 leading-relaxed text-ink-2">{r.body}</p>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <div>
          <p className="label mb-2 text-ok">Pros</p>
          <ul className="space-y-1.5 text-sm">
            {r.pros.map((p) => (
              <li key={p} className="flex gap-2">
                <span className="mt-2 h-px w-3 shrink-0 bg-ok" aria-hidden /> {p}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="label mb-2 text-danger">Cons</p>
          <ul className="space-y-1.5 text-sm">
            {r.cons.map((p) => (
              <li key={p} className="flex gap-2">
                <span className="mt-2 h-px w-3 shrink-0 bg-danger" aria-hidden /> {p}
              </li>
            ))}
          </ul>
        </div>
      </div>
      <div className="mt-5 border-l-2 border-ink/40 pl-4">
        <p className="label mb-1">Verdict</p>
        <p className="text-ink">{r.verdict}</p>
      </div>
      {r.inspectionNotes && (
        <div className="mt-5 rounded-plate border border-ink/10 bg-surface-2 p-4">
          <p className="label mb-1">3D inspection notes</p>
          <p className="text-sm leading-relaxed text-ink-2">{r.inspectionNotes}</p>
        </div>
      )}
    </article>
  );
}

/** What published reviewers and testers say, with every source linked. */
export function RoundupBlock({ racket }: { racket: Racket }) {
  const x = racket.roundup;
  if (!x) return null;
  return (
    <article>
      <div className="flex flex-wrap items-center gap-2">
        {x.status === "reviewed" ? (
          <span className="badge">
            {x.sources.length} {x.sources.length === 1 ? "source" : "sources"} summarised
          </span>
        ) : (
          <span className="badge badge-warn">Too new for a full review</span>
        )}
        <span className="text-xs text-ink-3">Checked {formatDate(x.checkedOn)}</span>
      </div>
      <p className="mt-3 max-w-[68ch] text-[1.0625rem] leading-relaxed text-ink/90">{x.summary}</p>

      <div className="mt-6 grid gap-6 sm:grid-cols-2">
        <div>
          <p className="label mb-2 text-ok">What testers like</p>
          <ul className="space-y-2 text-sm leading-snug">
            {x.liked.map((p) => (
              <li key={p} className="flex gap-2.5">
                <Icon name="check" size={16} className="mt-px shrink-0 text-ok" /> {p}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="label mb-2 text-danger">Watch out for</p>
          <ul className="space-y-2 text-sm leading-snug">
            {x.watchOuts.map((p) => (
              <li key={p} className="flex gap-2.5">
                <Icon name="minus" size={16} className="mt-px shrink-0 text-danger" /> {p}
              </li>
            ))}
          </ul>
        </div>
      </div>

      <dl className="mt-6 border-t border-ink/10">
        <div className="grid grid-cols-[minmax(0,9rem)_1fr] gap-4 border-b border-ink/10 py-3">
          <dt className="text-sm text-ink-2">Suits</dt>
          <dd className="text-ink">{x.suits}</dd>
        </div>
        {x.facts.map((f) => (
          <div key={f.label} className="grid grid-cols-[minmax(0,9rem)_1fr] gap-4 border-b border-ink/10 py-3">
            <dt className="text-sm text-ink-2">{f.label}</dt>
            <dd className="text-ink">{f.value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-6 rounded-plate border border-ink/10 bg-surface-2 p-5">
        <p className="label mb-1.5">Paladex&rsquo;s read</p>
        <p className="title text-[1.35rem] leading-snug text-ink">{x.ourRead}</p>
        <p className="mt-2 text-xs text-ink-3">Our opinion, drawn from the sources below. We haven&rsquo;t play-tested this racket.</p>
      </div>

      <div className="mt-5">
        <p className="label mb-2">Sources</p>
        <ul className="flex flex-wrap gap-2">
          {x.sources.map((s) => (
            <li key={s.url}>
              <a
                href={s.url}
                target="_blank"
                rel="nofollow noopener noreferrer"
                className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-white/12 px-3.5 py-1.5 text-sm text-ink-2 transition-colors hover:border-white/25 hover:text-ink"
              >
                {s.name} <Icon name="external" size={14} />
                <span className="sr-only"> (opens in a new tab)</span>
              </a>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

export function ModelInfo({ racket }: { racket: Racket }) {
  const m = racket.model;
  const status = m?.status ?? "unavailable";
  const info = MODEL_STATUS_INFO[status];
  return (
    <div className="plate p-5">
      <div className="flex flex-wrap items-center gap-2">
        <ProvenanceBadge status={status} long />
      </div>
      <p className="mt-3 text-sm leading-relaxed text-ink-2">{info.description}</p>
      {m && status !== "unavailable" && (
        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
          <dt className="text-ink-3">Source</dt>
          <dd className="text-ink/90">{m.provenance.source ?? "—"}</dd>
          <dt className="text-ink-3">Model version</dt>
          <dd className="num text-ink/90">{m.version}</dd>
          <dt className="text-ink-3">Download size</dt>
          <dd className="num text-ink/90">{m.fileSizeBytes ? `${Math.round(m.fileSizeBytes / 1024)} KB` : "—"}</dd>
          {racket.review?.modelQualityNote && (
            <>
              <dt className="text-ink-3">Model notes</dt>
              <dd className="text-ink/90">{racket.review.modelQualityNote}</dd>
            </>
          )}
        </dl>
      )}
      <Link href="/legal/3d-assets" className="mt-4 inline-block text-sm text-court underline">
        How our 3D models are made and labelled
      </Link>
    </div>
  );
}

export function Gallery({ racket }: { racket: Racket }) {
  if (!racket.images.length) return null;
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {racket.images.map((img) => (
        <li key={img.url} className="stage-sky relative aspect-square overflow-hidden rounded-plate border border-ink/8">
          <Image src={img.url} alt={img.alt} fill sizes="(max-width: 640px) 50vw, 240px" className="object-contain p-3" />
        </li>
      ))}
    </ul>
  );
}
