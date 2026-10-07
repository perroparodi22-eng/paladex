"use client";
/**
 * The studio stage. The racket stands in a black studio under one soft key
 * light, with a cool rim light that traces its edge and a soft shadow on an
 * invisible floor. Nothing else is in the frame. The light preset swaps the
 * studio for a white one (to judge colours on a bright background).
 */
import { useMemo } from "react";
import { ContactShadows, Environment, Lightformer } from "@react-three/drei";
import type { LightingPreset } from "../types";
import type { QualitySettings } from "../quality";

export interface StudioPalette {
  /** Canvas clear colour (matches the CSS backdrop behind the canvas). */
  background: string;
  key: string;
  keyIntensity: number;
  rimIntensity: number;
  fillIntensity: number;
  hemiSky: string;
  hemiGround: string;
  hemiIntensity: number;
  shadowColor: string;
  shadowOpacity: number;
  exposure: number;
}

export const PALETTES: Record<LightingPreset, StudioPalette> = {
  dark: {
    background: "#070809",
    key: "#ffffff",
    keyIntensity: 2.2,
    rimIntensity: 2.4,
    fillIntensity: 0.55,
    hemiSky: "#d9dde6",
    hemiGround: "#0b0c0e",
    hemiIntensity: 0.45,
    shadowColor: "#000000",
    shadowOpacity: 0.85,
    exposure: 1.05,
  },
  light: {
    background: "#e7e8eb",
    key: "#ffffff",
    keyIntensity: 1.6,
    rimIntensity: 1.2,
    fillIntensity: 0.8,
    hemiSky: "#ffffff",
    hemiGround: "#b9bcc4",
    hemiIntensity: 0.9,
    shadowColor: "#2a2d33",
    shadowOpacity: 0.42,
    exposure: 1.0,
  },
};

export function paletteFor(preset: LightingPreset): StudioPalette {
  return PALETTES[preset] ?? PALETTES.dark;
}

export function Stage({
  preset,
  palette,
  quality,
  stage,
  floorY,
  extent,
  shadowKey,
  envReady = true,
}: {
  preset: LightingPreset;
  palette: StudioPalette;
  quality: QualitySettings;
  stage: boolean;
  floorY: number;
  extent: number;
  shadowKey: string;
  /** Mount the environment only once its shaders are compiled (see pmrem-warmup). */
  envReady?: boolean;
}) {
  const dark = preset === "dark";
  const shadowScale = useMemo(() => extent * 1.5, [extent]);
  return (
    <>
      {/* Reflections: a large soft box above, two strip lights for the rim, a low fill. */}
      {envReady && (
        <Environment key={preset} resolution={quality.envResolution} frames={1}>
          <Lightformer form="rect" intensity={dark ? 2.2 : 1.6} color="#ffffff" scale={[6, 3, 1]} position={[0, 4, 1]} rotation-x={Math.PI / 2} />
          <Lightformer form="rect" intensity={dark ? 3 : 1.4} color="#e8eefc" scale={[0.6, 5, 1]} position={[-3, 1, -1.5]} rotation-y={Math.PI / 3} />
          <Lightformer form="rect" intensity={dark ? 2.4 : 1.2} color="#fff6ee" scale={[0.6, 5, 1]} position={[3, 1, -1.5]} rotation-y={-Math.PI / 3} />
          <Lightformer form="rect" intensity={dark ? 0.5 : 1} color="#ffffff" scale={[4, 2, 1]} position={[0, 0.5, 3.5]} />
        </Environment>
      )}

      {/* Key light from above and slightly in front. */}
      <directionalLight position={[0.8, 3.2, 2.2]} intensity={palette.keyIntensity} color={palette.key} />
      {/* Rim lights behind the racket trace its silhouette. */}
      <directionalLight position={[-2.4, 1.2, -2]} intensity={palette.rimIntensity} color="#dfe7ff" />
      <directionalLight position={[2.4, 1, -2]} intensity={palette.rimIntensity * 0.7} color="#fff1e4" />
      {/* Soft front fill so the face never drops to black. */}
      <directionalLight position={[0, 0.4, 3]} intensity={palette.fillIntensity} />
      <hemisphereLight args={[palette.hemiSky, palette.hemiGround, palette.hemiIntensity]} />

      {stage && quality.shadows && (
        <ContactShadows
          key={`${shadowKey}-${preset}`}
          position={[0, floorY + 0.002, 0]}
          scale={shadowScale}
          blur={2.8}
          far={extent * 1.1}
          opacity={palette.shadowOpacity}
          frames={1}
          resolution={512}
          color={palette.shadowColor}
        />
      )}
    </>
  );
}
