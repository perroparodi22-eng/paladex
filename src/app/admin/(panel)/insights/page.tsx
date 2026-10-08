import type { Metadata } from "next";
import { clickStats } from "@/server/repositories/affiliate";
import { eventCounts, recentEvents } from "@/server/repositories/events";

export const metadata: Metadata = { title: "Clicks and events" };

const when = (d: Date | number | string) => new Date(d).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

export default async function AdminInsights() {
  const [clicks, events, recent] = await Promise.all([clickStats(30), eventCounts(30), recentEvents(30)]);
  const totalClicks = clicks.byProduct.reduce((s, r) => s + r.clicks, 0);
  const placeholderClicks = clicks.byProduct.reduce((s, r) => s + (r.placeholder ?? 0), 0);
  return (
    <main>
      <h1 className="display text-5xl">Clicks and events</h1>
      <p className="mt-3 max-w-3xl text-ink-2">
        The last 30 days. Clicks are counted by the affiliate redirect; events by the first-party analytics endpoint. Neither stores IP
        addresses, cookies or user agents.
      </p>

      <dl className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ["Outbound clicks", totalClicks],
          ["Clicks on links not live yet", placeholderClicks],
          ["Event types", events.length],
          ["Events", events.reduce((s, e) => s + e.n, 0)],
        ].map(([k, v]) => (
          <div key={k as string} className="plate p-4">
            <dt className="label">{k}</dt>
            <dd className="num mt-1 text-3xl font-bold">{v}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <section className="plate p-5" aria-labelledby="by-racket">
          <h2 id="by-racket" className="title text-xl">
            Clicks by racket
          </h2>
          <Table head={["Racket", "Clicks", "Not live yet"]} rows={clicks.byProduct.map((r) => [r.name ?? `#${r.productId}`, r.clicks, r.placeholder ?? 0])} empty="No clicks yet." />
        </section>
        <section className="plate p-5" aria-labelledby="by-retailer">
          <h2 id="by-retailer" className="title text-xl">
            Clicks by retailer
          </h2>
          <Table head={["Retailer", "Clicks"]} rows={clicks.byRetailer.map((r) => [r.retailer, r.clicks])} empty="No clicks yet." />
        </section>
        <section className="plate p-5" aria-labelledby="events">
          <h2 id="events" className="title text-xl">
            Events
          </h2>
          <Table head={["Event", "Count"]} rows={events.map((e) => [e.name, e.n])} empty="No events yet. First-party analytics must be on (NEXT_PUBLIC_ANALYTICS_PROVIDER=first-party)." />
        </section>
        <section className="plate p-5" aria-labelledby="recent">
          <h2 id="recent" className="title text-xl">
            Latest events
          </h2>
          <Table
            head={["When", "Event", "Page"]}
            rows={recent.map((e) => [when(e.createdAt), e.name, e.path ?? "—"])}
            empty="Nothing recorded yet."
          />
        </section>
      </div>
    </main>
  );
}

function Table({ head, rows, empty }: { head: string[]; rows: Array<Array<string | number>>; empty: string }) {
  if (!rows.length) return <p className="mt-3 text-sm text-ink-2">{empty}</p>;
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-ink/8 text-left text-ink-2">
            {head.map((h, i) => (
              <th key={h} scope="col" className={i === 0 ? "py-2 pr-3 font-semibold" : "py-2 pl-3 text-right font-semibold"}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-ink/6 last:border-0">
              {r.map((c, j) => (
                <td key={j} className={j === 0 ? "py-2 pr-3" : "num py-2 pl-3 text-right"}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
