import { ImageResponse } from "next/og";
import { racketSvgDataUri } from "@/lib/racket-svg";
import { siteConfig } from "@/config/site";

export const alt = `${siteConfig.name}: the 3D padel racket database`;
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function Image() {
  const a = racketSvgDataUri("diamond", { face: "#16181c", frame: "#0b0b0c", accent: "#dcef4a", accent2: "#eef1ec", grip: "#111214", pattern: "sweep", holes: "hex", bridge: false });
  const b = racketSvgDataUri("round", { face: "#c9cdd1", frame: "#1a1d22", accent: "#2f6bff", accent2: "#0e2e57", grip: "#111214", pattern: "border", holes: "rings", bridge: false });
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          background: "linear-gradient(180deg, #a6b0ea 0%, #efb5b3 42%, #ffd1a6 66%, #ffe2c4 70%, #4d6be3 71%, #2343d6 100%)",
          color: "#11163a",
          padding: 64,
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", flex: 1 }}>
          <div style={{ fontSize: 120, fontWeight: 800, lineHeight: 0.9, textTransform: "" }}>{siteConfig.name}</div>
          <div style={{ fontSize: 40, marginTop: 24, color: "#9ba5b0" }}>Explore the racket that fits your game.</div>
          <div style={{ fontSize: 28, marginTop: 32, color: "#ffffff" }}>Every racket in 3D. Find your match.</div>
        </div>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={b} width={220} height={377} alt="" style={{ marginRight: -40, opacity: 0.8 }} />
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={a} width={280} height={480} alt="" />
      </div>
    ),
    size,
  );
}
