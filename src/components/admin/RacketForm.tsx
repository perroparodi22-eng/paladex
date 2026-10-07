"use client";
/**
 * The racket editor. One draft object holds the whole racket (product,
 * manufacturer specs, platform scores, look, 3D model and its annotations,
 * photos, offers, review). Saving sends it as JSON to a server action that
 * validates everything again and writes it in one transaction.
 */
import Link from "next/link";
import { useActionState, useEffect, useMemo, useRef, useState, useTransition } from "react";
import type { RacketInput } from "@/server/validation/admin";
import { deleteRacket, deriveAnnotations, saveRacket, type FormState } from "@/app/admin/actions";
import {
  APPROVAL_STATUSES,
  BALANCES,
  BASES,
  CAMERA_VIEWS,
  HARDNESSES,
  LICENSE_STATUSES,
  MODEL_STATUSES,
  OVERLAY_KINDS,
  PLAYER_LEVELS,
  PLAYING_STYLES,
  RACKET_SHAPES,
  SPEC_KEYS,
  STOCK_STATUSES,
  SURFACE_FINISHES,
  VERIFICATION_STATES,
} from "@/domain/types";
import {
  BALANCE_INFO,
  BASIS_INFO,
  HARDNESS_INFO,
  LEVEL_INFO,
  MODEL_STATUS_INFO,
  OVERLAY_INFO,
  SCORE_INFO,
  SCORE_KEYS,
  SHAPE_INFO,
  STOCK_INFO,
  STYLE_INFO,
  SURFACE_INFO,
  VERIFICATION_INFO,
  VIEW_INFO,
} from "@/domain/vocab";
import { Racket3DViewer } from "@/components/three/Racket3DViewer";
import { Icon, type IconName } from "@/components/ui/Icon";
import { AFFILIATE_PLACEHOLDER, isPlaceholderLink } from "@/lib/urls";
import { racketInertia } from "@/lib/racket-physics";
import { cn } from "@/lib/cn";
import { ChipGroup, ColorInput, NumberInput, RowActions, Section, Select, TextArea, TextInput, Toggle, UploadButton } from "./fields";

type Draft = RacketInput;
type ListKey = "hotspots" | "annotations" | "overlays" | "images" | "offers";

const opts = <T extends string>(values: readonly T[], label: (v: T) => string) => values.map((v) => ({ value: v, label: label(v) }));
const LICENSE_LABEL: Record<string, string> = {
  owned: "Owned by us",
  licensed: "Licensed",
  permission: "Used with permission",
  supplied: "Supplied by the owner",
  pending: "Pending",
  none: "None",
};
const slugify = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);

const NAV = [
  ["basics", "Basics"],
  ["specs", "Specs"],
  ["scores", "Scores"],
  ["look", "Look"],
  ["model", "3D model"],
  ["annotations", "Hotspots"],
  ["photos", "Photos"],
  ["offers", "Offers"],
  ["review", "Review"],
] as const;

export function RacketForm({
  initial,
  brands,
  retailers,
}: {
  initial: Draft;
  brands: Array<{ id: number; name: string; slug: string }>;
  retailers: Array<{ id: number; name: string; isDemo: boolean; currency: string }>;
}) {
  const [d, setD] = useState<Draft>(initial);
  const [state, action, pending] = useActionState<FormState, FormData>(saveRacket, null);
  const [slugTouched, setSlugTouched] = useState(!!initial.id);
  const [deriving, startDerive] = useTransition();
  const [deriveMsg, setDeriveMsg] = useState<string | null>(null);
  const savedJson = useRef(JSON.stringify(initial));
  const submitted = useRef<string | null>(null);
  const json = JSON.stringify(d);
  const dirty = json !== savedJson.current;

  // A successful save makes the submitted draft the new clean state.
  useEffect(() => {
    if (state?.ok && submitted.current) savedJson.current = submitted.current;
  }, [state]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (json !== savedJson.current) e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [json]);

  const patch = <K extends keyof Draft>(k: K, p: Partial<NonNullable<Draft[K]>>) => setD((x) => ({ ...x, [k]: { ...(x[k] as object), ...p } }));
  const list = <K extends ListKey>(k: K) => d[k] as Draft[K];
  const setList = <K extends ListKey>(k: K, items: Draft[K]) => setD((x) => ({ ...x, [k]: items }));
  const updateAt = <K extends ListKey>(k: K, i: number, p: Partial<Draft[K][number]>) =>
    setList(k, (list(k) as Array<Draft[K][number]>).map((it, j) => (j === i ? { ...it, ...p } : it)) as Draft[K]);
  const removeAt = <K extends ListKey>(k: K, i: number) => setList(k, (list(k) as Array<Draft[K][number]>).filter((_, j) => j !== i) as Draft[K]);
  const move = <K extends ListKey>(k: K, i: number, dir: -1 | 1) => {
    const arr = [...(list(k) as Array<Draft[K][number]>)];
    const j = i + dir;
    if (j < 0 || j >= arr.length) return;
    [arr[i], arr[j]] = [arr[j], arr[i]];
    setList(k, arr as Draft[K]);
  };

  const brand = brands.find((b) => b.id === d.basics.brandId);
  const setName = (name: string) =>
    setD((x) => ({ ...x, basics: { ...x.basics, name, slug: slugTouched ? x.basics.slug : slugify(`${brand?.slug ?? ""} ${name}`) } }));

  const regenerate = () => {
    if (!window.confirm("Replace the hotspots, 3D notes and overlays with ones generated from the current specs? Unsaved edits to them will be lost.")) return;
    setDeriveMsg(null);
    startDerive(async () => {
      const res = await deriveAnnotations({
        id: d.id,
        slug: d.basics.slug,
        sweetSpot: d.evaluation.sweetSpot,
        modelStatus: d.model.status,
        modelUrl: d.model.url,
        specs: d.specs,
      });
      if (!res.ok) {
        setDeriveMsg(res.message);
        return;
      }
      setD((x) => ({ ...x, hotspots: res.hotspots, annotations: res.annotations, overlays: res.overlays }));
      setDeriveMsg("Regenerated from the specs. Review them, then save.");
    });
  };

  /* ------------------------------------------------------- checklist */
  const checklist = useMemo(() => {
    const items: Array<{ tone: "ok" | "warn" | "bad"; text: string }> = [];
    if (!d.basics.name || !d.basics.slug) items.push({ tone: "bad", text: "Give the racket a name and a URL slug." });
    if (!d.basics.shortDescription) items.push({ tone: "warn", text: "Add a short description: it shows on cards and in search results." });
    items.push(
      d.specs.verification === "verified"
        ? { tone: "ok", text: "Specs are marked verified." }
        : { tone: "warn", text: `Specs are marked "${VERIFICATION_INFO[d.specs.verification].label.toLowerCase()}". The page says so.` },
    );
    if (d.evaluation.isSample) items.push({ tone: "warn", text: "Scores are labelled as a sample evaluation." });
    const m = d.model.status;
    if (m === "unavailable") items.push({ tone: "warn", text: "No 3D model: the page shows a picture and “3D coming soon”." });
    else if (m === "placeholder") items.push({ tone: "warn", text: "The 3D model is a placeholder, and every viewer labels it as one." });
    else items.push({ tone: "ok", text: `3D model: ${MODEL_STATUS_INFO[m].label.toLowerCase()}.` });
    if (m !== "unavailable" && !d.model.url) items.push({ tone: "bad", text: "Add the model file, or set the model to “No model yet”." });
    if (m !== "unavailable" && d.model.approvalStatus !== "approved") items.push({ tone: "warn", text: `3D model approval: ${d.model.approvalStatus}.` });
    const noLink = d.offers.filter((o) => isPlaceholderLink(o.affiliateUrl)).length;
    if (!d.offers.length) items.push({ tone: "warn", text: "No offers yet: the page says it isn't available from our retailers yet." });
    if (noLink) items.push({ tone: "warn", text: `${noLink} offer${noLink > 1 ? "s have" : " has"} no live affiliate link. Their buttons explain the link isn't active yet.` });
    const demo = d.offers.filter((o) => o.isDemo).length;
    if (demo) items.push({ tone: "warn", text: `${demo} demo offer${demo > 1 ? "s" : ""}: labelled as sample prices and kept out of search results.` });
    if (d.images.some((i) => i.alt.trim().length < 3)) items.push({ tone: "bad", text: "Every photo needs alt text (what it shows)." });
    if (d.review?.isSample) items.push({ tone: "warn", text: "The editorial review is labelled as a sample." });
    return items;
  }, [d]);

  const preview = {
    slug: d.basics.slug || "draft",
    fullName: `${brand?.name ?? ""} ${d.basics.name || "New racket"}`,
    shape: d.specs.shape,
    visual: d.visual,
    imageUrl: d.images[0]?.url ?? null,
    imageAlt: d.images[0]?.alt ?? "Racket photo",
    model: d.model.status !== "unavailable" && d.model.url ? { status: d.model.status, url: d.model.url, previewUrl: d.model.previewUrl, posterUrl: d.model.posterUrl, supportsExplode: d.model.supportsExplode } : null,
    hotspots: d.hotspots.map((h, i) => ({ ...h, id: i })),
    annotations: d.annotations.map((a, i) => ({ ...a, id: i })),
    overlays: d.overlays.filter((o) => o.enabled).map((o) => ({ kind: o.kind, basis: o.basis, note: o.note, params: o.params })),
    surfaceFinish: d.specs.surfaceFinish,
    inertia: racketInertia(d.specs),
  };

  const tone: Record<"ok" | "warn" | "bad", { icon: IconName; cls: string }> = {
    ok: { icon: "check", cls: "text-ok" },
    warn: { icon: "info", cls: "text-warn" },
    bad: { icon: "warning", cls: "text-danger" },
  };

  return (
    <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <form
        action={action}
        onSubmit={() => {
          submitted.current = json;
        }}
        className="min-w-0 space-y-5 pb-28"
      >
        <input type="hidden" name="payload" value={json} />

        <nav aria-label="Form sections" className="no-scrollbar sticky top-0 z-20 -mx-1 flex gap-1 overflow-x-auto bg-ground/95 px-1 py-2">
          {NAV.map(([id, label]) => (
            <a key={id} href={`#${id}`} className="chip shrink-0 min-h-9">
              {label}
            </a>
          ))}
        </nav>

        {/* ------------------------------------------------------ basics */}
        <Section id="basics" title="Basics">
          <div className="grid gap-4 sm:grid-cols-2">
            <Select label="Brand" value={String(d.basics.brandId)} onChange={(v) => v && patch("basics", { brandId: Number(v) })} options={brands.map((b) => ({ value: String(b.id), label: b.name }))} />
            <TextInput label="Name" value={d.basics.name} onChange={setName} required maxLength={120} placeholder="Metalbone 3.4" />
            <TextInput
              label="URL slug"
              value={d.basics.slug}
              onChange={(v) => {
                setSlugTouched(true);
                patch("basics", { slug: v.toLowerCase() });
              }}
              hint={
                <>
                  The page lives at <span className="num">/rackets/{d.basics.slug || "…"}</span>. Lowercase letters, numbers and dashes.
                </>
              }
            />
            <TextInput label="Collection or line" value={d.basics.collection} onChange={(v) => patch("basics", { collection: v || null })} placeholder="Metalbone" />
            <NumberInput label="Year" value={d.basics.year} onChange={(v) => patch("basics", { year: v })} min={1990} max={2100} />
            <NumberInput label="Indicative price" value={d.basics.indicativePriceEur} onChange={(v) => patch("basics", { indicativePriceEur: v })} min={1} max={5000} suffix="EUR" hint="Shown only when no retailer offer is available." />
            <TextArea className="sm:col-span-2" label="Short description" value={d.basics.shortDescription} onChange={(v) => patch("basics", { shortDescription: v })} rows={2} maxLength={300} hint="One sentence for cards and search results." />
            <TextArea className="sm:col-span-2" label="Description" value={d.basics.description} onChange={(v) => patch("basics", { description: v })} rows={5} maxLength={5000} />
            <ChipGroup label="Levels" values={d.basics.levels} onChange={(v) => patch("basics", { levels: v })} options={opts(PLAYER_LEVELS, (v) => LEVEL_INFO[v].label)} max={3} />
            <ChipGroup label="Playing styles" values={d.basics.styles} onChange={(v) => patch("basics", { styles: v })} options={opts(PLAYING_STYLES, (v) => STYLE_INFO[v].label)} max={5} />
            <Select label="Status" value={d.basics.status} onChange={(v) => v && patch("basics", { status: v })} options={[{ value: "draft", label: "Draft (not public)" }, { value: "published", label: "Published" }]} />
            <Select label="Data quality" value={d.basics.dataStatus} onChange={(v) => v && patch("basics", { dataStatus: v })} options={opts(VERIFICATION_STATES, (v) => VERIFICATION_INFO[v].label)} />
            <Toggle label="Featured" checked={d.basics.featured} onChange={(v) => patch("basics", { featured: v })} hint="Shown first on the homepage and in the showroom." />
            <Toggle label="Mark as new" checked={d.basics.isNew} onChange={(v) => patch("basics", { isNew: v })} />
          </div>
        </Section>

        {/* ------------------------------------------------------- specs */}
        <Section id="specs" title="Manufacturer specification" intro="What the manufacturer publishes. Leave a field empty when it is not published; the site shows a dash, never a guess.">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Select label="Shape" value={d.specs.shape} onChange={(v) => v && patch("specs", { shape: v })} options={opts(RACKET_SHAPES, (v) => SHAPE_INFO[v].label)} />
            <NumberInput label="Weight from" value={d.specs.weightMinG} onChange={(v) => patch("specs", { weightMinG: v })} min={250} max={450} suffix="g" />
            <NumberInput label="Weight to" value={d.specs.weightMaxG} onChange={(v) => patch("specs", { weightMaxG: v })} min={250} max={450} suffix="g" />
            <Select label="Balance" value={d.specs.balance} onChange={(v) => patch("specs", { balance: v })} options={opts(BALANCES, (v) => BALANCE_INFO[v].label)} allowNone="Not published" />
            <NumberInput label="Balance point" value={d.specs.balanceMm} onChange={(v) => patch("specs", { balanceMm: v })} min={200} max={320} suffix="mm" hint="From the butt cap, if published." />
            <Select label="Core feel" value={d.specs.hardness} onChange={(v) => patch("specs", { hardness: v })} options={opts(HARDNESSES, (v) => HARDNESS_INFO[v].label)} allowNone="Not published" />
            <NumberInput label="Thickness" value={d.specs.thicknessMm} onChange={(v) => patch("specs", { thicknessMm: v })} min={20} max={40} step={0.5} suffix="mm" />
            <Select label="Surface" value={d.specs.surfaceFinish} onChange={(v) => patch("specs", { surfaceFinish: v })} options={opts(SURFACE_FINISHES, (v) => SURFACE_INFO[v].label)} allowNone="Not published" />
            <TextInput label="Frame material" value={d.specs.frameMaterial} onChange={(v) => patch("specs", { frameMaterial: v || null })} />
            <TextInput label="Face material" value={d.specs.faceMaterial} onChange={(v) => patch("specs", { faceMaterial: v || null })} />
            <TextInput label="Core material" value={d.specs.coreMaterial} onChange={(v) => patch("specs", { coreMaterial: v || null })} />
            <Select label="Verification" value={d.specs.verification} onChange={(v) => v && patch("specs", { verification: v })} options={opts(VERIFICATION_STATES, (v) => VERIFICATION_INFO[v].label)} />
            <TextArea className="sm:col-span-2" label="Source note" value={d.specs.sourceNote} onChange={(v) => patch("specs", { sourceNote: v || null })} rows={2} hint="Where these numbers come from (shown under the spec table)." />
            <TextInput label="Source URL" type="url" value={d.specs.sourceUrl} onChange={(v) => patch("specs", { sourceUrl: v || null })} placeholder="https://" />
          </div>
        </Section>

        {/* ------------------------------------------------------ scores */}
        <Section id="scores" title="Platform evaluation" intro="Our own 1–10 scores. They are always labelled as the platform's evaluation, never as measurements.">
          <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
            {SCORE_KEYS.map((k) => (
              <label key={k} className="grid grid-cols-[8rem_1fr_3rem] items-center gap-3 text-sm">
                <span className="font-semibold text-ink">{SCORE_INFO[k].label}</span>
                <input
                  type="range"
                  min={1}
                  max={10}
                  step={0.1}
                  value={d.evaluation[k]}
                  onChange={(e) => patch("evaluation", { [k]: Number(e.target.value) } as Partial<Draft["evaluation"]>)}
                  aria-label={`${SCORE_INFO[k].label} score`}
                />
                <span className="num text-right font-bold">{d.evaluation[k].toFixed(1)}</span>
              </label>
            ))}
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-3">
            <TextArea label="Best for" value={d.evaluation.bestFor} onChange={(v) => patch("evaluation", { bestFor: v })} rows={2} maxLength={300} />
            <TextArea label="Recommended for" value={d.evaluation.recommendedFor} onChange={(v) => patch("evaluation", { recommendedFor: v })} rows={2} maxLength={500} />
            <TextArea label="Not ideal for" value={d.evaluation.notIdealFor} onChange={(v) => patch("evaluation", { notIdealFor: v })} rows={2} maxLength={300} />
          </div>
          <div className="mt-4">
            <Toggle label="Sample evaluation" checked={d.evaluation.isSample} onChange={(v) => patch("evaluation", { isSample: v })} hint="Keep on until the racket has been properly evaluated." />
          </div>
        </Section>

        {/* -------------------------------------------------------- look */}
        <Section id="look" title="Look" intro="Colours and print used for the illustration and the generated placeholder model.">
          <div className="grid gap-4 sm:grid-cols-3 lg:grid-cols-5">
            {(["face", "frame", "accent", "accent2", "grip"] as const).map((k) => (
              <ColorInput key={k} label={k === "accent2" ? "Second accent" : k[0].toUpperCase() + k.slice(1)} value={d.visual[k]} onChange={(v) => patch("visual", { [k]: v } as Partial<Draft["visual"]>)} />
            ))}
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <Select label="Print pattern" value={d.visual.pattern} onChange={(v) => v && patch("visual", { pattern: v })} options={opts(["sweep", "split", "chevron", "ring", "border", "blade"] as const, (v) => v[0].toUpperCase() + v.slice(1))} />
            <Select label="Hole pattern" value={d.visual.holes} onChange={(v) => v && patch("visual", { holes: v })} options={[{ value: "hex", label: "Hexagonal grid" }, { value: "rings", label: "Rings" }]} />
            <div className="pt-6">
              <Toggle label="Throat bridge" checked={d.visual.bridge} onChange={(v) => patch("visual", { bridge: v })} />
            </div>
          </div>
        </Section>

        {/* ------------------------------------------------------- model */}
        <Section id="model" title="3D model" intro="Upload a GLB (preferred) or a self-contained GLTF, or paste the URL of a file already on your asset storage. The status says honestly where it comes from.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Select label="Where the model comes from" value={d.model.status} onChange={(v) => v && patch("model", { status: v })} options={opts(MODEL_STATUSES, (v) => MODEL_STATUS_INFO[v].label)} />
            <div className="flex items-end gap-3">
              <UploadButton kind="model" hint={d.basics.slug} label="Upload model" onUploaded={(url) => patch("model", { url, status: d.model.status === "unavailable" ? "platform" : d.model.status })} />
              <UploadButton kind="model" hint={`${d.basics.slug}-preview`} label="Upload light version" onUploaded={(url) => patch("model", { previewUrl: url })} />
            </div>
            <TextInput label="Model URL" value={d.model.url} onChange={(v) => patch("model", { url: v || null })} placeholder="/models/platform/your-racket.glb" hint="A site path or an https URL on a host listed in ASSET_ORIGINS." />
            <TextInput label="Light version URL" value={d.model.previewUrl} onChange={(v) => patch("model", { previewUrl: v || null })} hint="Optional smaller file shown first on phones and slow connections." />
            <TextInput label="Poster image URL" value={d.model.posterUrl} onChange={(v) => patch("model", { posterUrl: v || null })} hint="Shown before the model loads. Defaults to the first photo." />
            <TextInput label="Version" value={d.model.version} onChange={(v) => patch("model", { version: v })} hint="Bump it when you replace the file so browsers fetch the new one." />
            <Select label="Licence" value={d.model.licenseStatus} onChange={(v) => v && patch("model", { licenseStatus: v })} options={opts(LICENSE_STATUSES, (v) => LICENSE_LABEL[v])} />
            <Select label="Approval" value={d.model.approvalStatus} onChange={(v) => v && patch("model", { approvalStatus: v })} options={opts(APPROVAL_STATUSES, (v) => v[0].toUpperCase() + v.slice(1))} />
            <TextInput label="Source" value={d.model.source} onChange={(v) => patch("model", { source: v || null })} placeholder="Modelled from photos supplied by…" />
            <TextInput label="Creator" value={d.model.creator} onChange={(v) => patch("model", { creator: v || null })} />
            <TextInput label="Attribution" value={d.model.attribution} onChange={(v) => patch("model", { attribution: v || null })} />
            <TextInput label="Usage restrictions" value={d.model.usageRestrictions} onChange={(v) => patch("model", { usageRestrictions: v || null })} />
            <TextArea className="sm:col-span-2" label="Notes" value={d.model.notes} onChange={(v) => patch("model", { notes: v || null })} rows={2} />
            <Toggle label="Has separate parts for the layers view" checked={d.model.supportsExplode} onChange={(v) => patch("model", { supportsExplode: v })} hint="Needs part_* names in the file (see docs/3D-PIPELINE.md)." />
          </div>
          {d.model.status === "unavailable" && d.model.url && (
            <p role="alert" className="mt-4 rounded-2xl bg-warn-fill px-4 py-3 text-sm text-warn">
              A model file is set but the status is &ldquo;No model yet&rdquo;. Choose where the model comes from, or clear the URL.
            </p>
          )}
        </Section>

        {/* ------------------------------------------- hotspots and notes */}
        <Section
          id="annotations"
          title="Hotspots, 3D notes and overlays"
          intro="Hotspots pin explanations to points on the model (u across, v from butt to tip, w from back to front, all 0–1). Notes caption each camera view."
          action={
            <button type="button" className="btn btn-secondary btn-sm" onClick={regenerate} disabled={deriving}>
              <Icon name="spark" size={16} /> {deriving ? "Generating…" : "Regenerate from specs"}
            </button>
          }
        >
          {deriveMsg && (
            <p role="status" className="mb-4 rounded-2xl bg-court-tint px-4 py-2.5 text-sm text-court-deep">
              {deriveMsg}
            </p>
          )}
          <h3 className="title mb-3 text-lg">Hotspots</h3>
          <ol className="space-y-3">
            {d.hotspots.map((h, i) => (
              <li key={i} className="rounded-3xl border border-ink/8 p-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <p className="flex items-center gap-2 font-semibold">
                    <span className="grid h-7 w-7 place-items-center rounded-full bg-court text-xs text-on-court">{i + 1}</span>
                    {h.label || "New hotspot"}
                  </p>
                  <RowActions label={`hotspot ${i + 1}`} onUp={i > 0 ? () => move("hotspots", i, -1) : undefined} onDown={i < d.hotspots.length - 1 ? () => move("hotspots", i, 1) : undefined} onRemove={() => removeAt("hotspots", i)} />
                </div>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <TextInput label="Label" value={h.label} onChange={(v) => updateAt("hotspots", i, { label: v })} />
                  <TextInput label="Key" value={h.key} onChange={(v) => updateAt("hotspots", i, { key: slugify(v) })} />
                  <Select label="Camera view" value={h.view} onChange={(v) => v && updateAt("hotspots", i, { view: v })} options={opts(CAMERA_VIEWS, (v) => VIEW_INFO[v].label)} />
                  <Select label="Basis" value={h.basis} onChange={(v) => v && updateAt("hotspots", i, { basis: v })} options={opts(BASES, (v) => BASIS_INFO[v].label)} />
                  <NumberInput label="u (across)" value={h.u} onChange={(v) => updateAt("hotspots", i, { u: v ?? 0.5 })} step={0.01} min={-0.5} max={1.5} />
                  <NumberInput label="v (butt → tip)" value={h.v} onChange={(v) => updateAt("hotspots", i, { v: v ?? 0.5 })} step={0.01} min={-0.5} max={1.5} />
                  <NumberInput label="w (back → front)" value={h.w} onChange={(v) => updateAt("hotspots", i, { w: v ?? 1 })} step={0.01} min={-0.5} max={1.5} />
                  <Select label="Spec it explains" value={h.specKey} onChange={(v) => updateAt("hotspots", i, { specKey: v })} options={opts(SPEC_KEYS, (v) => v)} allowNone="None" />
                  <TextArea className="sm:col-span-2 lg:col-span-4" label="Text" value={h.body} onChange={(v) => updateAt("hotspots", i, { body: v })} rows={2} maxLength={800} />
                </div>
              </li>
            ))}
          </ol>
          <button
            type="button"
            className="btn btn-ghost btn-sm mt-3"
            disabled={d.hotspots.length >= 20}
            onClick={() => setList("hotspots", [...d.hotspots, { key: `point-${d.hotspots.length + 1}`, label: "", body: "", u: 0.5, v: 0.6, w: 1, view: "front", specKey: null, basis: "platform" }])}
          >
            <Icon name="plus" size={16} /> Add hotspot
          </button>

          <h3 className="title mb-3 mt-8 text-lg">3D notes</h3>
          <ol className="space-y-3">
            {d.annotations.map((a, i) => (
              <li key={i} className="rounded-3xl border border-ink/8 p-4">
                <div className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
                  <TextInput label="Title" value={a.title} onChange={(v) => updateAt("annotations", i, { title: v })} />
                  <Select label="Camera view" value={a.view} onChange={(v) => v && updateAt("annotations", i, { view: v })} options={opts(CAMERA_VIEWS, (v) => VIEW_INFO[v].label)} />
                  <Select label="Basis" value={a.basis} onChange={(v) => v && updateAt("annotations", i, { basis: v })} options={opts(BASES, (v) => BASIS_INFO[v].label)} />
                  <div className="pt-6">
                    <RowActions label={`note ${i + 1}`} onRemove={() => removeAt("annotations", i)} />
                  </div>
                  <TextArea className="sm:col-span-4" label="Text" value={a.body} onChange={(v) => updateAt("annotations", i, { body: v })} rows={2} maxLength={800} />
                </div>
              </li>
            ))}
          </ol>
          <button
            type="button"
            className="btn btn-ghost btn-sm mt-3"
            disabled={d.annotations.length >= 20}
            onClick={() => setList("annotations", [...d.annotations, { view: "front", title: "", body: "", basis: "platform" }])}
          >
            <Icon name="plus" size={16} /> Add note
          </button>

          <h3 className="title mb-3 mt-8 text-lg">Overlays</h3>
          <ul className="space-y-3">
            {d.overlays.map((o, i) => (
              <li key={o.kind} className="rounded-3xl border border-ink/8 p-4">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                  <Toggle label={OVERLAY_INFO[o.kind].label} checked={o.enabled} onChange={(v) => updateAt("overlays", i, { enabled: v })} hint={OVERLAY_INFO[o.kind].description} />
                  <RowActions label={`${OVERLAY_INFO[o.kind].label} overlay`} onRemove={() => removeAt("overlays", i)} />
                </div>
                <div className="grid gap-3 sm:grid-cols-[12rem_1fr]">
                  <Select label="Basis" value={o.basis} onChange={(v) => v && updateAt("overlays", i, { basis: v })} options={opts(BASES, (v) => BASIS_INFO[v].label)} />
                  <TextInput label="Note shown with the overlay" value={o.note} onChange={(v) => updateAt("overlays", i, { note: v || null })} />
                  <ParamsEditor value={o.params} onChange={(params) => updateAt("overlays", i, { params })} />
                </div>
              </li>
            ))}
          </ul>
          {d.overlays.length < OVERLAY_KINDS.length && (
            <div className="mt-3 flex flex-wrap gap-2">
              {OVERLAY_KINDS.filter((k) => !d.overlays.some((o) => o.kind === k)).map((k) => (
                <button key={k} type="button" className="btn btn-ghost btn-sm" onClick={() => setList("overlays", [...d.overlays, { kind: k, enabled: true, basis: "illustrative", note: null, params: {} }])}>
                  <Icon name="plus" size={16} /> {OVERLAY_INFO[k].label}
                </button>
              ))}
            </div>
          )}
        </Section>

        {/* ------------------------------------------------------ photos */}
        <Section
          id="photos"
          title="Photos"
          intro="The first photo is the poster on cards. Every photo needs alt text and a note on where it comes from."
          action={
            <UploadButton
              kind="image"
              hint={d.basics.slug}
              label="Upload photo"
              onUploaded={(url) =>
                setList("images", [...d.images, { url, alt: "", kind: d.images.length ? "angle" : "front", source: null, licenseStatus: "pending", attribution: null, creator: null, usageRestrictions: null, approvalStatus: "pending" }])
              }
            />
          }
        >
          {d.images.length === 0 && <p className="text-sm text-ink-2">No photos yet. Cards and posters use the generated illustration.</p>}
          <ol className="space-y-3">
            {d.images.map((im, i) => (
              <li key={i} className="grid gap-4 rounded-3xl border border-ink/8 p-4 sm:grid-cols-[120px_1fr]">
                <div className="card-sky relative h-36 overflow-hidden rounded-2xl">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  {im.url && <img src={im.url} alt="" className="absolute inset-0 h-full w-full object-contain p-2" />}
                </div>
                <div className="grid gap-3 sm:grid-cols-2">
                  <TextInput className="sm:col-span-2" label="Image URL" value={im.url} onChange={(v) => updateAt("images", i, { url: v })} />
                  <TextInput className="sm:col-span-2" label="Alt text" value={im.alt} onChange={(v) => updateAt("images", i, { alt: v })} maxLength={200} hint="Describe what the photo shows." />
                  <Select label="Kind" value={im.kind} onChange={(v) => v && updateAt("images", i, { kind: v })} options={opts(["front", "angle", "detail", "lifestyle"] as const, (v) => v[0].toUpperCase() + v.slice(1))} />
                  <Select label="Licence" value={im.licenseStatus} onChange={(v) => v && updateAt("images", i, { licenseStatus: v })} options={opts(LICENSE_STATUSES, (v) => LICENSE_LABEL[v])} />
                  <TextInput label="Source" value={im.source} onChange={(v) => updateAt("images", i, { source: v || null })} />
                  <Select label="Approval" value={im.approvalStatus} onChange={(v) => v && updateAt("images", i, { approvalStatus: v })} options={opts(APPROVAL_STATUSES, (v) => v[0].toUpperCase() + v.slice(1))} />
                  <div className="sm:col-span-2 flex justify-end">
                    <RowActions label={`photo ${i + 1}`} onUp={i > 0 ? () => move("images", i, -1) : undefined} onDown={i < d.images.length - 1 ? () => move("images", i, 1) : undefined} onRemove={() => removeAt("images", i)} />
                  </div>
                </div>
              </li>
            ))}
          </ol>
          <button
            type="button"
            className="btn btn-ghost btn-sm mt-3"
            onClick={() => setList("images", [...d.images, { url: "", alt: "", kind: "front", source: null, licenseStatus: "pending", attribution: null, creator: null, usageRestrictions: null, approvalStatus: "pending" }])}
          >
            <Icon name="plus" size={16} /> Add photo by URL
          </button>
        </Section>

        {/* ------------------------------------------------------ offers */}
        <Section id="offers" title="Offers" intro={<>One offer per retailer. Leave the affiliate link empty (or {AFFILIATE_PLACEHOLDER}) until you have a real one: the site then says the link isn&apos;t active yet instead of sending people nowhere.</>}>
          {retailers.length === 0 && (
            <p className="text-sm text-ink-2">
              Add a retailer first on{" "}
              <Link href="/admin/retailers" className="text-court underline">
                Retailers
              </Link>
              .
            </p>
          )}
          <ol className="space-y-3">
            {d.offers.map((o, i) => (
              <li key={o.id ?? `new-${i}`} className="rounded-3xl border border-ink/8 p-4">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Select label="Retailer" value={String(o.retailerId)} onChange={(v) => v && updateAt("offers", i, { retailerId: Number(v) })} options={retailers.map((r) => ({ value: String(r.id), label: `${r.name}${r.isDemo ? " (demo)" : ""}` }))} />
                  <NumberInput label="Price" value={o.priceEur} onChange={(v) => updateAt("offers", i, { priceEur: v ?? 0 })} min={0.5} max={5000} step={0.01} suffix={o.currency} />
                  <Select label="Stock" value={o.stockStatus} onChange={(v) => v && updateAt("offers", i, { stockStatus: v })} options={opts(STOCK_STATUSES, (v) => STOCK_INFO[v])} />
                  <TextInput label="Currency" value={o.currency} onChange={(v) => updateAt("offers", i, { currency: v.toUpperCase().slice(0, 3) })} />
                  <TextInput className="sm:col-span-2" label="Affiliate link" value={o.affiliateUrl} onChange={(v) => updateAt("offers", i, { affiliateUrl: v || null })} placeholder={AFFILIATE_PLACEHOLDER} hint="Must point to one of the retailer's allowed domains." />
                  <TextInput className="sm:col-span-2" label="Product page (without tracking)" value={o.productUrl} onChange={(v) => updateAt("offers", i, { productUrl: v || null })} placeholder="https://" />
                  <TextInput className="sm:col-span-2" label="Shipping note" value={o.shippingInfo} onChange={(v) => updateAt("offers", i, { shippingInfo: v || null })} />
                  <div className="flex flex-wrap items-center gap-5 sm:col-span-2">
                    <Toggle label="Available" checked={o.available} onChange={(v) => updateAt("offers", i, { available: v })} />
                    <Toggle label="Demo price" checked={o.isDemo} onChange={(v) => updateAt("offers", i, { isDemo: v })} />
                    <Toggle label="Active" checked={o.active} onChange={(v) => updateAt("offers", i, { active: v })} />
                    <span className="ml-auto">
                      <RowActions label={`offer ${i + 1}`} onRemove={() => removeAt("offers", i)} />
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ol>
          {retailers.length > 0 && (
            <button
              type="button"
              className="btn btn-ghost btn-sm mt-3"
              disabled={d.offers.length >= retailers.length}
              onClick={() => {
                const free = retailers.find((r) => !d.offers.some((o) => o.retailerId === r.id));
                if (!free) return;
                setList("offers", [
                  ...d.offers,
                  { retailerId: free.id, productUrl: null, affiliateUrl: null, priceEur: d.basics.indicativePriceEur ?? 100, currency: free.currency, stockStatus: "unknown", available: true, shippingInfo: null, isDemo: free.isDemo, active: true },
                ]);
              }}
            >
              <Icon name="plus" size={16} /> Add offer
            </button>
          )}
        </Section>

        {/* ------------------------------------------------------ review */}
        <Section id="review" title="Editorial review" intro="Optional. Never invent test results: describe what you actually observed.">
          <Toggle
            label="This racket has an editorial review"
            checked={!!d.review}
            onChange={(v) =>
              setD((x) => ({
                ...x,
                review: v ? (x.review ?? { title: "", summary: "", body: "", pros: [], cons: [], verdict: "", inspectionNotes: null, modelQualityNote: null, isSample: true }) : null,
              }))
            }
          />
          {d.review && (
            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <TextInput className="sm:col-span-2" label="Title" value={d.review.title} onChange={(v) => patch("review", { title: v })} />
              <TextArea className="sm:col-span-2" label="Summary" value={d.review.summary} onChange={(v) => patch("review", { summary: v })} rows={2} />
              <TextArea className="sm:col-span-2" label="Body" value={d.review.body} onChange={(v) => patch("review", { body: v })} rows={6} />
              <TextArea label="Pros (one per line)" value={d.review.pros.join("\n")} onChange={(v) => patch("review", { pros: v.split("\n").map((s) => s.trim()).filter(Boolean).slice(0, 10) })} rows={4} />
              <TextArea label="Cons (one per line)" value={d.review.cons.join("\n")} onChange={(v) => patch("review", { cons: v.split("\n").map((s) => s.trim()).filter(Boolean).slice(0, 10) })} rows={4} />
              <TextArea className="sm:col-span-2" label="Verdict" value={d.review.verdict} onChange={(v) => patch("review", { verdict: v })} rows={2} />
              <TextArea label="3D inspection notes" value={d.review.inspectionNotes} onChange={(v) => patch("review", { inspectionNotes: v || null })} rows={3} />
              <TextArea label="Note on the 3D model's quality" value={d.review.modelQualityNote} onChange={(v) => patch("review", { modelQualityNote: v || null })} rows={3} />
              <Toggle label="Sample review" checked={d.review.isSample} onChange={(v) => patch("review", { isSample: v })} />
            </div>
          )}
        </Section>

        {/* ---------------------------------------------------- save bar */}
        <div className="fixed inset-x-0 bottom-0 z-40 px-3 pb-3 lg:left-[232px]">
          <div className="plate mx-auto flex max-w-[1400px] flex-wrap items-center justify-between gap-3 rounded-full px-4 py-2.5 shadow-lift">
            <p role="status" aria-live="polite" className={cn("min-w-0 truncate text-sm", state && !state.ok ? "text-danger" : state?.ok && !dirty ? "text-ok" : "text-ink-2")}>
              {state && (!dirty || !state.ok) ? state.message : dirty ? "Unsaved changes" : "All changes saved"}
            </p>
            <div className="flex items-center gap-2">
              {d.id && (
                <Link href={`/admin/rackets/${d.id}/preview`} className="btn btn-ghost btn-sm" target="_blank">
                  <Icon name="eye" size={16} /> Preview
                </Link>
              )}
              {d.id && initial.basics.status === "published" && (
                <Link href={`/rackets/${initial.basics.slug}`} className="btn btn-ghost btn-sm hidden sm:inline-flex" target="_blank">
                  <Icon name="external" size={16} /> Live page
                </Link>
              )}
              <button type="submit" className="btn btn-primary btn-sm" disabled={pending}>
                {pending ? "Saving…" : d.basics.status === "published" ? "Save and publish" : "Save draft"}
              </button>
            </div>
          </div>
        </div>
      </form>

      {/* Live preview and checklist. */}
      <aside className="space-y-4 xl:sticky xl:top-4 xl:self-start" aria-label="Live preview">
        <div className="relative h-[460px] overflow-hidden rounded-[28px] shadow-lift">
          <Racket3DViewer key={`${d.model.url ?? "none"}-${d.model.status}`} racket={preview} variant="showroom" loadStrategy="visible" className="absolute inset-0" />
        </div>
        <div className="plate p-5">
          <h2 className="title text-lg">Before you publish</h2>
          <ul className="mt-3 space-y-2.5">
            {checklist.map((c) => (
              <li key={c.text} className="flex gap-2.5 text-sm leading-snug">
                <Icon name={tone[c.tone].icon} size={16} className={cn("mt-0.5 shrink-0", tone[c.tone].cls)} />
                <span className={c.tone === "bad" ? "text-danger" : "text-ink-2"}>{c.text}</span>
              </li>
            ))}
          </ul>
        </div>
        {d.id && (
          <form
            action={deleteRacket}
            onSubmit={(e) => {
              if (!window.confirm(`Delete ${d.basics.name || "this racket"} for good? Its page, model links, photos and offers go with it. Click history is kept.`)) e.preventDefault();
            }}
            className="plate p-5"
          >
            <input type="hidden" name="id" value={d.id} />
            <h2 className="title text-lg">Delete</h2>
            <p className="mt-1 text-sm text-ink-2">Removes the racket and everything attached to it. This can&apos;t be undone.</p>
            <button type="submit" className="btn btn-sm mt-3 border-danger/40 text-danger hover:bg-danger hover:text-white">
              <Icon name="trash" size={16} /> Delete racket
            </button>
          </form>
        )}
      </aside>
    </div>
  );
}

/** Overlay parameters as JSON (advanced). Applied only when it parses. */
function ParamsEditor({ value, onChange }: { value: Record<string, number | string | boolean>; onChange: (v: Record<string, number | string | boolean>) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value));
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="sm:col-span-2">
      <label className="mb-1.5 block text-[0.8125rem] font-semibold text-ink">
        Parameters (JSON, advanced)
        <textarea
          rows={2}
          className={cn("field num mt-1.5 font-normal", error && "border-danger")}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={() => {
            try {
              const parsed = JSON.parse(text || "{}");
              if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Use an object");
              setError(null);
              onChange(parsed);
            } catch {
              setError("Not valid JSON. It wasn't applied.");
            }
          }}
        />
      </label>
      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  );
}
