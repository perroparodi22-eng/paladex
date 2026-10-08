import { ImageResponse } from "next/og";
import { getRacket } from "@/server/repositories/rackets";
import { racketSvgDataUri } from "@/lib/racket-svg";
import { SHAPE_INFO } from "@/domain/vocab";
import { siteConfig } from "@/config/site";

export const alt = "Padel racket in 3D";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const r = await getRacket(slug);
  const name = r ? r.name : "Padel racket";
  const brand = r ? r.brand.name : siteConfig.name;
  const src = r ? racketSvgDataUri(r.specs.shape, r.visual) : null;
  const facts = r
    ? [
        ["Shape", SHAPE_INFO[r.specs.shape].label],
        ["Weight", r.specs.weightMinG ? `${r.specs.weightMinG}–${r.specs.weightMaxG} g` : "—"],
        ["Power", r.evaluation ? r.evaluation.power.toFixed(1) : "—"],
        ["Control", r.evaluation ? r.evaluation.control.toFixed(1) : "—"],
      ]
    : [];
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          background: "linear-gradient(180deg, #a6b0ea 0%, #efb5b3 42%, #ffd1a6 66%, #ffe2c4 70%, #4d6be3 71%, #2343d6 100%)",
          color: "#11163a",
          padding: 56,
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", flex: 1 }}>
          <div style={{ display: "flex", fontSize: 26, letterSpacing: 4, textTransform: "", color: "#9ba5b0" }}>{siteConfig.name} · 3D padel racket database</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 34, color: "#9ba5b0" }}>{brand}</div>
            <div style={{ fontSize: 96, fontWeight: 800, lineHeight: 0.95, textTransform: "" }}>{name}</div>
            <div style={{ display: "flex", gap: 28, marginTop: 28 }}>
              {facts.map(([k, v]) => (
                <div key={k} style={{ display: "flex", flexDirection: "column", borderTop: "2px solid rgba(238,241,236,0.3)", paddingTop: 10, minWidth: 150 }}>
                  <div style={{ fontSize: 20, color: "#9ba5b0", textTransform: "", letterSpacing: 2 }}>{k}</div>
                  <div style={{ fontSize: 36, fontWeight: 700 }}>{v}</div>
                </div>
              ))}
            </div>
          </div>
          <div style={{ display: "flex", fontSize: 24, color: "#ffffff" }}>Turn it in 3D. Find your match.</div>
        </div>
        {src && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} width={300} height={514} alt="" style={{ marginLeft: 40 }} />
        )}
      </div>
    ),
    size,
  );
}
