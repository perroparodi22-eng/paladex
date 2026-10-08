import { ImageResponse } from "next/og";
import { getRacket } from "@/server/repositories/rackets";
import { racketSvgDataUri } from "@/lib/racket-svg";
import { SHAPE_INFO } from "@/domain/vocab";
import { siteConfig } from "@/config/site";
import { OG } from "@/lib/og";

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
          backgroundColor: OG.ground,
          backgroundImage: OG.stage("82%"),
          color: OG.ink,
          padding: 56,
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between", flex: 1 }}>
          <div style={{ display: "flex", fontSize: 26, letterSpacing: 4, color: OG.ink3 }}>{siteConfig.name} · 3D padel racket database</div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            <div style={{ fontSize: 34, color: OG.ink2 }}>{brand}</div>
            <div style={{ fontSize: 96, fontWeight: 800, lineHeight: 0.95, letterSpacing: -3 }}>{name}</div>
            <div style={{ display: "flex", gap: 28, marginTop: 28 }}>
              {facts.map(([k, v]) => (
                <div key={k} style={{ display: "flex", flexDirection: "column", borderTop: `2px solid ${OG.rule}`, paddingTop: 10, minWidth: 150 }}>
                  <div style={{ fontSize: 20, color: OG.ink3, letterSpacing: 2 }}>{k}</div>
                  <div style={{ fontSize: 36, fontWeight: 700 }}>{v}</div>
                </div>
              ))}
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {r?.evaluation && <div style={{ display: "flex", fontSize: 18, color: OG.ink3, marginBottom: 10 }}>Power and control: Paladex platform scores (sample), not manufacturer data.</div>}
            <div style={{ display: "flex", fontSize: 24, color: OG.ink2 }}>Turn it in 3D. Find your match.</div>
          </div>
        </div>
        {src && (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", marginLeft: 40 }}>
            <img src={src} width={300} height={514} alt="" />
            <div style={{ display: "flex", ...OG.shadow, marginTop: -6 }} />
          </div>
        )}
      </div>
    ),
    size,
  );
}
