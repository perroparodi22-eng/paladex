import type { Metadata } from "next";
import Link from "next/link";
import { adminDashboardStats } from "@/server/repositories/admin";
import { MODEL_STATUS_INFO } from "@/domain/vocab";
import { MODEL_STATUSES } from "@/domain/types";

export const metadata: Metadata = { title: "Overview" };

export default async function AdminOverview() {
  const s = await adminDashboardStats();
  const tiles = [
    { label: "Published rackets", value: s.published },
    { label: "Drafts", value: s.drafts },
    { label: "Offers", value: s.offers.total },
    { label: "Offers without a live affiliate link", value: s.offers.placeholder, warn: s.offers.placeholder > 0 },
    { label: "Demo offers", value: s.offers.demo, warn: s.offers.demo > 0 },
    { label: "Outbound clicks (30 days)", value: s.clicks30 },
    { label: "Analytics events (30 days)", value: s.events30 },
  ];
  return (
    <main>
      <h1 className="display text-5xl mb-6">Overview</h1>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-plate border border-ink/8 bg-ink/8 sm:grid-cols-4">
        {tiles.map((t) => (
          <div key={t.label} className="bg-surface p-4">
            <dt className="label">{t.label}</dt>
            <dd className={`num mt-1 text-3xl font-bold ${t.warn ? "text-warn" : ""}`}>{t.value}</dd>
          </div>
        ))}
      </dl>

      <h2 className="display mt-10 text-3xl mb-4">3D models</h2>
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {MODEL_STATUSES.map((st) => (
          <li key={st} className="flex items-baseline justify-between gap-4 border-b border-ink/8 py-2">
            <span className="text-ink-2">{MODEL_STATUS_INFO[st].label}</span>
            <span className="num text-lg font-semibold">{s.models[st] ?? 0}</span>
          </li>
        ))}
      </ul>

      <p className="mt-10 max-w-2xl text-sm leading-relaxed text-ink-2">
        Placeholder and demo offers are shown on the site as &ldquo;link not active yet&rdquo; and &ldquo;demo&rdquo;, and demo prices are kept out of search
        results. Replace them with real retailer links before launch. <Link href="/" className="text-court underline-offset-4 hover:underline">View the site</Link>
      </p>
    </main>
  );
}
