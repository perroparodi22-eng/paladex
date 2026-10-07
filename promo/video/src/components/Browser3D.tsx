// A floating browser window in 3D space that shows the real site. Place it inside
// <Space3D> (which sets the perspective). Content is laid out at the captured page
// size (default 1920×1080 CSS px) and the whole window is transformed in 3D, so
// <Cursor> and callouts placed inside `children` stay glued to the page.
import React from "react";
import { AbsoluteFill } from "remotion";
import { C, FONT } from "../theme";

export const CHROME_H = 56;

export const Space3D: React.FC<{ children: React.ReactNode; perspective?: number; originX?: number; originY?: number; style?: React.CSSProperties }> = ({
  children,
  perspective = 2200,
  originX = 50,
  originY = 45,
  style,
}) => (
  <AbsoluteFill style={{ perspective, perspectiveOrigin: `${originX}% ${originY}%`, transformStyle: "preserve-3d", ...style }}>{children}</AbsoluteFill>
);

export type Pose = {
  /** Centre offset from the frame centre, px. */
  x?: number;
  y?: number;
  z?: number;
  rotateX?: number; // deg
  rotateY?: number; // deg
  rotateZ?: number; // deg
  scale?: number;
};

export const poseTransform = ({ x = 0, y = 0, z = 0, rotateX = 0, rotateY = 0, rotateZ = 0, scale = 1 }: Pose) =>
  `translate3d(${x}px, ${y}px, ${z}px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) rotateZ(${rotateZ}deg) scale(${scale})`;

export const Browser3D: React.FC<
  Pose & {
    children: React.ReactNode;
    /** Page viewport size in CSS px (the capture size). */
    pageWidth?: number;
    pageHeight?: number;
    /** Text after the brand in the address bar, e.g. "/rackets". */
    path?: string;
    opacity?: number;
    /** 0–1 strength of the moving glass glare. */
    glare?: number;
    /** Hide the window chrome (just a floating screen). */
    bare?: boolean;
    radius?: number;
  }
> = ({ children, pageWidth = 1920, pageHeight = 1080, path = "", opacity = 1, glare = 1, bare = false, radius = 22, ...pose }) => {
  const chrome = bare ? 0 : CHROME_H;
  const w = pageWidth;
  const h = pageHeight + chrome;
  // Glare follows the window's yaw so the glass catches the light as it turns.
  const g = 50 - (pose.rotateY ?? 0) * 2.2 + (pose.rotateX ?? 0) * 0.8;
  return (
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: "50%",
        width: w,
        height: h,
        marginLeft: -w / 2,
        marginTop: -h / 2,
        transformStyle: "preserve-3d",
        transform: poseTransform(pose),
        opacity,
      }}
    >
      {/* Back plate: gives the slab thickness when it turns. */}
      <div style={{ position: "absolute", inset: 0, borderRadius: radius, background: "#050607", transform: "translateZ(-16px)", boxShadow: "0 80px 160px rgba(0,0,0,0.75), 0 30px 60px rgba(0,0,0,0.5)" }} />
      <div style={{ position: "absolute", inset: 0, borderRadius: radius, background: "#0c0d10", transform: "translateZ(-8px)" }} />
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: radius,
          overflow: "hidden",
          background: C.ground,
          boxShadow: "0 0 0 1.5px rgba(255,255,255,0.10), inset 0 1px 0 rgba(255,255,255,0.06)",
        }}
      >
        {!bare && <ChromeBar path={path} />}
        <div style={{ position: "absolute", left: 0, top: chrome, width: pageWidth, height: pageHeight, overflow: "hidden" }}>{children}</div>
        {glare > 0 && (
          <AbsoluteFill
            style={{
              pointerEvents: "none",
              background: `linear-gradient(115deg, rgba(255,255,255,0) ${g - 22}%, rgba(255,255,255,${0.07 * glare}) ${g}%, rgba(255,255,255,0) ${g + 18}%)`,
              mixBlendMode: "screen",
            }}
          />
        )}
      </div>
    </div>
  );
};

const ChromeBar: React.FC<{ path: string }> = ({ path }) => (
  <div style={{ position: "absolute", left: 0, top: 0, right: 0, height: CHROME_H, background: "#101215", borderBottom: "1px solid rgba(255,255,255,0.06)", display: "flex", alignItems: "center" }}>
    <div style={{ display: "flex", gap: 10, marginLeft: 24 }}>
      {[0, 1, 2].map((i) => (
        <div key={i} style={{ width: 14, height: 14, borderRadius: 7, background: "#2b2f36" }} />
      ))}
    </div>
    <div
      style={{
        position: "absolute",
        left: "50%",
        top: 10,
        height: CHROME_H - 20,
        width: 560,
        marginLeft: -280,
        borderRadius: 999,
        background: "#1a1d22",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 10,
        fontFamily: FONT,
        fontSize: 18,
        color: C.ink3,
        letterSpacing: "0.01em",
      }}
    >
      <svg width="14" height="16" viewBox="0 0 14 16" fill="none">
        <rect x="1" y="7" width="12" height="8" rx="2" fill="#878d98" />
        <path d="M4 7V5a3 3 0 0 1 6 0v2" stroke="#878d98" strokeWidth="1.8" />
      </svg>
      <span style={{ color: C.ink, fontWeight: 560 }}>paladex</span>
      <span>{path}</span>
    </div>
  </div>
);
