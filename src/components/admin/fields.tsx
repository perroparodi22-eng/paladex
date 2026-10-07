"use client";
/**
 * Small, labelled form controls for the admin. Every control has a visible
 * label; hints sit under it. Values are controlled by the racket form state.
 */
import { useId, useRef, useState, type ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

export function Field({ label, hint, children, className }: { label: string; hint?: ReactNode; children: (id: string) => ReactNode; className?: string }) {
  const id = useId();
  return (
    <div className={cn("min-w-0", className)}>
      <label htmlFor={id} className="mb-1.5 block text-[0.8125rem] font-semibold text-ink [--rond:100]">
        {label}
      </label>
      {children(id)}
      {hint && <p className="mt-1 text-xs leading-relaxed text-ink-3">{hint}</p>}
    </div>
  );
}

export function TextInput({
  label,
  value,
  onChange,
  hint,
  placeholder,
  className,
  type = "text",
  required,
  maxLength,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (v: string) => void;
  hint?: ReactNode;
  placeholder?: string;
  className?: string;
  type?: "text" | "url";
  required?: boolean;
  maxLength?: number;
}) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(id) => <input id={id} type={type} className="field" value={value ?? ""} placeholder={placeholder} required={required} maxLength={maxLength} onChange={(e) => onChange(e.target.value)} />}
    </Field>
  );
}

export function TextArea({
  label,
  value,
  onChange,
  hint,
  rows = 3,
  className,
  maxLength,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (v: string) => void;
  hint?: ReactNode;
  rows?: number;
  className?: string;
  maxLength?: number;
}) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(id) => <textarea id={id} rows={rows} className="field min-h-0 resize-y leading-relaxed" value={value ?? ""} maxLength={maxLength} onChange={(e) => onChange(e.target.value)} />}
    </Field>
  );
}

export function NumberInput({
  label,
  value,
  onChange,
  hint,
  min,
  max,
  step,
  className,
  suffix,
}: {
  label: string;
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  hint?: ReactNode;
  min?: number;
  max?: number;
  step?: number;
  className?: string;
  suffix?: string;
}) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(id) => (
        <div className="relative">
          <input
            id={id}
            type="number"
            inputMode="decimal"
            className={cn("field num", suffix && "pr-12")}
            value={value ?? ""}
            min={min}
            max={max}
            step={step}
            onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          />
          {suffix && <span className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-sm text-ink-3">{suffix}</span>}
        </div>
      )}
    </Field>
  );
}

export function Select<T extends string>({
  label,
  value,
  onChange,
  options,
  hint,
  className,
  allowNone,
}: {
  label: string;
  value: T | null | undefined;
  onChange: (v: T | null) => void;
  options: ReadonlyArray<{ value: T; label: string }>;
  hint?: ReactNode;
  className?: string;
  allowNone?: string;
}) {
  return (
    <Field label={label} hint={hint} className={className}>
      {(id) => (
        <div className="relative">
          <select id={id} className="field appearance-none pr-10" value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : (e.target.value as T))}>
            {allowNone !== undefined && <option value="">{allowNone}</option>}
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <Icon name="chevronDown" size={16} className="pointer-events-none absolute right-4 top-1/2 -translate-y-1/2 text-ink-2" />
        </div>
      )}
    </Field>
  );
}

export function Toggle({ label, checked, onChange, hint }: { label: string; checked: boolean; onChange: (v: boolean) => void; hint?: ReactNode }) {
  const id = useId();
  return (
    <div className="flex items-start gap-3">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={cn("relative mt-0.5 h-7 w-12 shrink-0 rounded-full transition-colors", checked ? "bg-court" : "bg-ink/15")}
      >
        <span className={cn("absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-[left] duration-200", checked ? "left-6" : "left-1")} />
      </button>
      <label htmlFor={id} className="cursor-pointer text-sm">
        <span className="font-semibold text-ink">{label}</span>
        {hint && <span className="block text-xs text-ink-3">{hint}</span>}
      </label>
    </div>
  );
}

export function ChipGroup<T extends string>({ label, values, onChange, options, max }: { label: string; values: T[]; onChange: (v: T[]) => void; options: ReadonlyArray<{ value: T; label: string }>; max?: number }) {
  return (
    <fieldset>
      <legend className="mb-1.5 text-[0.8125rem] font-semibold text-ink [--rond:100]">{label}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => {
          const on = values.includes(o.value);
          return (
            <button
              key={o.value}
              type="button"
              className="chip"
              aria-pressed={on}
              disabled={!on && max !== undefined && values.length >= max}
              onClick={() => onChange(on ? values.filter((v) => v !== o.value) : [...values, o.value])}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

export function ColorInput({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const id = useId();
  return (
    <div className="flex items-center gap-2.5">
      <input id={id} type="color" value={value} onChange={(e) => onChange(e.target.value)} className="h-10 w-12 cursor-pointer rounded-xl border border-ink/12 bg-surface p-1" />
      <label htmlFor={id} className="text-sm">
        <span className="block font-semibold text-ink">{label}</span>
        <span className="num text-xs text-ink-3">{value}</span>
      </label>
    </div>
  );
}

/**
 * Uploads a file to /api/admin/upload with a real progress bar. The server
 * checks the session, size, extension and content before storing it.
 */
export function UploadButton({ kind, hint, onUploaded, label }: { kind: "model" | "image"; hint: string; onUploaded: (url: string) => void; label: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const accept = kind === "model" ? ".glb,.gltf,model/gltf-binary,model/gltf+json" : ".png,.jpg,.jpeg,.webp,.avif,image/png,image/jpeg,image/webp,image/avif";
  const limit = kind === "model" ? 25 : 8;

  const upload = (file: File) => {
    setError(null);
    if (file.size > limit * 1024 * 1024) {
      setError(`That file is larger than ${limit} MB.`);
      return;
    }
    const body = new FormData();
    body.append("file", file);
    body.append("kind", kind);
    body.append("hint", hint || kind);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/admin/upload");
    xhr.upload.onprogress = (e) => e.lengthComputable && setProgress(e.loaded / e.total);
    xhr.onload = () => {
      setProgress(null);
      try {
        const json = JSON.parse(xhr.responseText) as { url?: string; error?: string };
        if (xhr.status >= 200 && xhr.status < 300 && json.url) onUploaded(json.url);
        else setError(json.error ?? `Upload failed (${xhr.status}).`);
      } catch {
        setError(`Upload failed (${xhr.status}).`);
      }
    };
    xhr.onerror = () => {
      setProgress(null);
      setError("The upload was interrupted. Check your connection and try again.");
    };
    setProgress(0);
    xhr.send(body);
  };

  return (
    <div>
      <input
        ref={input}
        type="file"
        accept={accept}
        className="sr-only"
        tabIndex={-1}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) upload(f);
          e.target.value = "";
        }}
      />
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => input.current?.click()} disabled={progress !== null}>
        <Icon name="upload" size={16} /> {progress !== null ? `Uploading ${Math.round(progress * 100)}%` : label}
      </button>
      {progress !== null && (
        <span className="mt-2 block h-1.5 w-48 overflow-hidden rounded-full bg-ink/8">
          <span className="block h-full rounded-full bg-court transition-[width]" style={{ width: `${Math.round(progress * 100)}%` }} />
        </span>
      )}
      {error && (
        <p role="alert" className="mt-1.5 text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

export function Section({ id, title, intro, children, action }: { id: string; title: string; intro?: ReactNode; children: ReactNode; action?: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="plate scroll-mt-28 p-5 sm:p-6">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={`${id}-title`} className="title text-2xl">
            {title}
          </h2>
          {intro && <p className="mt-1 max-w-2xl text-sm text-ink-2">{intro}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

export function RowActions({ onUp, onDown, onRemove, label }: { onUp?: () => void; onDown?: () => void; onRemove: () => void; label: string }) {
  return (
    <div className="flex gap-1">
      {onUp && (
        <button type="button" onClick={onUp} className="grid h-9 w-9 place-items-center rounded-full text-ink-2 hover:bg-ink/6 hover:text-ink" aria-label={`Move ${label} up`}>
          <Icon name="chevronUp" size={16} />
        </button>
      )}
      {onDown && (
        <button type="button" onClick={onDown} className="grid h-9 w-9 place-items-center rounded-full text-ink-2 hover:bg-ink/6 hover:text-ink" aria-label={`Move ${label} down`}>
          <Icon name="chevronDown" size={16} />
        </button>
      )}
      <button type="button" onClick={onRemove} className="grid h-9 w-9 place-items-center rounded-full text-danger hover:bg-danger/10" aria-label={`Remove ${label}`}>
        <Icon name="trash" size={16} />
      </button>
    </div>
  );
}
