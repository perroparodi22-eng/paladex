"use client";
/**
 * Inline editors for brands and retailers. Each row is its own small form
 * posting to a server action, so one save never touches another row.
 */
import { useActionState } from "react";
import { deleteBrand, deleteRetailer, saveBrand, saveRetailer, type FormState } from "@/app/admin/actions";
import { Icon } from "@/components/ui/Icon";
import { cn } from "@/lib/cn";

function Status({ state }: { state: FormState }) {
  if (!state) return null;
  return (
    <p role="status" className={cn("text-sm", state.ok ? "text-ok" : "text-danger")}>
      {state.message}
    </p>
  );
}

function Input({ label, name, defaultValue, hint, required, placeholder }: { label: string; name: string; defaultValue?: string | null; hint?: string; required?: boolean; placeholder?: string }) {
  return (
    <label className="block min-w-0">
      <span className="mb-1.5 block text-[0.8125rem] font-semibold text-ink">{label}</span>
      <input name={name} defaultValue={defaultValue ?? ""} required={required} placeholder={placeholder} className="field" />
      {hint && <span className="mt-1 block text-xs text-ink-3">{hint}</span>}
    </label>
  );
}

function Check({ label, name, defaultChecked, hint }: { label: string; name: string; defaultChecked: boolean; hint?: string }) {
  return (
    <label className="flex items-start gap-2.5 text-sm">
      <input type="checkbox" name={name} defaultChecked={defaultChecked} className="mt-0.5 h-4 w-4" />
      <span>
        <span className="font-semibold text-ink">{label}</span>
        {hint && <span className="block text-xs text-ink-3">{hint}</span>}
      </span>
    </label>
  );
}

export interface BrandRow {
  id?: number;
  slug: string;
  name: string;
  country: string | null;
  description: string;
  websiteUrl: string | null;
  logoUrl: string | null;
  rackets?: number;
}

export function BrandForm({ brand }: { brand?: BrandRow }) {
  const [state, action, pending] = useActionState<FormState, FormData>(saveBrand, null);
  const [delState, delAction, deleting] = useActionState<FormState, FormData>(deleteBrand, null);
  return (
    <div className="space-y-3">
      <form action={action} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {brand?.id && <input type="hidden" name="id" value={brand.id} />}
        <Input label="Name" name="name" defaultValue={brand?.name} required />
        <Input label="Slug" name="slug" defaultValue={brand?.slug} required hint="Used in /brands/slug. Lowercase and dashes." />
        <Input label="Country" name="country" defaultValue={brand?.country} />
        <label className="block sm:col-span-2 lg:col-span-3">
          <span className="mb-1.5 block text-[0.8125rem] font-semibold text-ink">Description</span>
          <textarea name="description" defaultValue={brand?.description ?? ""} rows={2} className="field resize-y" />
        </label>
        <Input label="Website" name="websiteUrl" defaultValue={brand?.websiteUrl} placeholder="https://" />
        <Input label="Logo URL" name="logoUrl" defaultValue={brand?.logoUrl} hint="Optional. A site path or an allowed https host." />
        <div className="flex items-end gap-3">
          <button type="submit" className="btn btn-primary btn-sm" disabled={pending}>
            {pending ? "Saving…" : brand?.id ? "Save brand" : "Add brand"}
          </button>
          <Status state={state} />
        </div>
      </form>
      {brand?.id && (
        <form
          action={delAction}
          onSubmit={(e) => {
            if (!window.confirm(`Delete ${brand.name}?`)) e.preventDefault();
          }}
          className="flex items-center gap-3"
        >
          <input type="hidden" name="id" value={brand.id} />
          <button type="submit" className="btn btn-ghost btn-sm text-danger" disabled={deleting || (brand.rackets ?? 0) > 0} title={(brand.rackets ?? 0) > 0 ? "Move or delete its rackets first" : undefined}>
            <Icon name="trash" size={16} /> Delete brand
          </button>
          {(brand.rackets ?? 0) > 0 && <span className="text-xs text-ink-3">Has {brand.rackets} racket(s), so it can&apos;t be deleted.</span>}
          <Status state={delState} />
        </form>
      )}
    </div>
  );
}

export interface RetailerRow {
  id?: number;
  slug: string;
  name: string;
  websiteUrl: string;
  logoUrl: string | null;
  country: string;
  currency: string;
  shippingInfo: string | null;
  affiliateNetwork: string | null;
  allowedDomains: string[];
  isDemo: boolean;
  active: boolean;
  offers?: number;
}

export function RetailerForm({ retailer }: { retailer?: RetailerRow }) {
  const [state, action, pending] = useActionState<FormState, FormData>(saveRetailer, null);
  const [delState, delAction, deleting] = useActionState<FormState, FormData>(deleteRetailer, null);
  return (
    <div className="space-y-3">
      <form action={action} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {retailer?.id && <input type="hidden" name="id" value={retailer.id} />}
        <Input label="Name" name="name" defaultValue={retailer?.name} required />
        <Input label="Slug" name="slug" defaultValue={retailer?.slug} required />
        <Input label="Website" name="websiteUrl" defaultValue={retailer?.websiteUrl} required placeholder="https://" />
        <label className="block sm:col-span-2 lg:col-span-3">
          <span className="mb-1.5 block text-[0.8125rem] font-semibold text-ink">Allowed link domains</span>
          <input name="allowedDomains" defaultValue={(retailer?.allowedDomains ?? []).join(", ")} className="field" placeholder="shop.example.com, *.example.com" />
          <span className="mt-1 block text-xs text-ink-3">
            The affiliate redirect only ever sends visitors to these domains (comma separated). An offer link anywhere else is treated as broken.
          </span>
        </label>
        <Input label="Country or region" name="country" defaultValue={retailer?.country ?? "EU"} required />
        <Input label="Currency" name="currency" defaultValue={retailer?.currency ?? "EUR"} required />
        <Input label="Affiliate network" name="affiliateNetwork" defaultValue={retailer?.affiliateNetwork} placeholder="Awin, CJ, Tradedoubler…" />
        <Input label="Shipping note" name="shippingInfo" defaultValue={retailer?.shippingInfo} />
        <Input label="Logo URL" name="logoUrl" defaultValue={retailer?.logoUrl} />
        <div className="flex flex-col justify-end gap-2">
          <Check label="Demo retailer" name="isDemo" defaultChecked={retailer?.isDemo ?? false} hint="Its prices are labelled as samples." />
          <Check label="Active" name="active" defaultChecked={retailer?.active ?? true} />
        </div>
        <div className="flex items-end gap-3 sm:col-span-2 lg:col-span-3">
          <button type="submit" className="btn btn-primary btn-sm" disabled={pending}>
            {pending ? "Saving…" : retailer?.id ? "Save retailer" : "Add retailer"}
          </button>
          <Status state={state} />
        </div>
      </form>
      {retailer?.id && (
        <form
          action={delAction}
          onSubmit={(e) => {
            if (!window.confirm(`Delete ${retailer.name} and its ${retailer.offers ?? 0} offer(s)?`)) e.preventDefault();
          }}
          className="flex items-center gap-3"
        >
          <input type="hidden" name="id" value={retailer.id} />
          <button type="submit" className="btn btn-ghost btn-sm text-danger" disabled={deleting}>
            <Icon name="trash" size={16} /> Delete retailer and its offers
          </button>
          <Status state={delState} />
        </form>
      )}
    </div>
  );
}
