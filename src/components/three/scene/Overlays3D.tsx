"use client";
/**
 * Technical overlays drawn in 3D, in model space: sweet spot, impact zone,
 * balance point, dimensions and weight distribution. Each one is labelled
 * in the DOM with its basis (manufacturer, platform estimate, illustration).
 */
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame, useThree } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import type { OverlayConfig, OverlayKind } from "@/domain/types";
import type { ModelFrame } from "../views";
import type { Anchor } from "../types";

const BALL = new THREE.Color("#d9f04a");
const SERVE = new THREE.Color("#5b78ff");
const LINE = "#ffffff";

const zoneVertex = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`;
const zoneFragment = /* glsl */ `
  varying vec2 vUv;
  uniform vec3 uColor;
  uniform float uFill;
  uniform float uDash;
  void main() {
    vec2 p = vUv - 0.5;
    float r = length(p) * 2.0;
    if (r > 1.02) discard;
    float core = pow(smoothstep(1.0, 0.0, r), 1.4) * uFill;
    float ring = smoothstep(0.045, 0.0, abs(r - 0.965));
    float dash = uDash > 0.5 ? step(0.45, fract(atan(p.y, p.x) / 6.28318 * 40.0)) : 1.0;
    gl_FragColor = vec4(uColor, clamp(core + ring * dash * 0.95, 0.0, 1.0));
  }
`;

function Zone({ cx, cy, z, rx, ry, color, fill, dashed, pulse }: { cx: number; cy: number; z: number; rx: number; ry: number; color: THREE.Color; fill: number; dashed: boolean; pulse: boolean }) {
  const mat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: zoneVertex,
        fragmentShader: zoneFragment,
        uniforms: { uColor: { value: color }, uFill: { value: fill }, uDash: { value: dashed ? 1 : 0 } },
        transparent: true,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        toneMapped: false,
        polygonOffset: true,
        polygonOffsetFactor: -2,
      }),
    [color, fill, dashed],
  );
  const ref = useRef<THREE.Mesh>(null);
  const invalidate = useThree((s) => s.invalidate);
  useFrame(({ clock }) => {
    if (!pulse || !ref.current) return;
    const s = 1 + Math.sin(clock.elapsedTime * 2.2) * 0.035;
    ref.current.scale.set(s, s, 1);
    invalidate();
  });
  useEffect(() => () => mat.dispose(), [mat]);
  return (
    <mesh ref={ref} position={[cx, cy, z]} material={mat} renderOrder={5}>
      <planeGeometry args={[rx * 2, ry * 2]} />
    </mesh>
  );
}

const barFragment = /* glsl */ `
  varying vec2 vUv;
  uniform float uCenter;
  uniform float uBias;
  void main() {
    float t = vUv.y;
    float mass = exp(-pow(t - uCenter, 2.0) / 0.035) * 0.75 + 0.25 * (0.5 + uBias * (t - 0.5));
    vec3 cold = vec3(0.05, 0.16, 0.33);
    vec3 hot = vec3(0.86, 0.94, 0.29);
    float edge = smoothstep(0.0, 0.08, vUv.x) * smoothstep(1.0, 0.92, vUv.x);
    gl_FragColor = vec4(mix(cold, hot, clamp(mass, 0.0, 1.0)), 0.9 * edge);
  }
`;

export function overlayAnchors(frame: ModelFrame, overlays: OverlayConfig[], active: OverlayKind[]): Anchor[] {
  const [x0, y0, z0] = frame.min;
  const [x1, y1, z1] = frame.max;
  const [w, h] = frame.size;
  const out: Anchor[] = [];
  for (const o of overlays) {
    if (!active.includes(o.kind)) continue;
    const p = o.params;
    if (o.kind === "sweet-spot" || o.kind === "impact-zone") {
      const cx = x0 + Number(p.u ?? 0.5) * w;
      const cy = y0 + Number(p.v ?? 0.6) * h;
      const ry = Number(p.rv ?? 0.1) * h;
      out.push({ key: `ov:${o.kind}`, position: [cx + (o.kind === "impact-zone" ? Number(p.ru ?? 0.1) * w * 0.7 : 0), cy + ry * (o.kind === "sweet-spot" ? 1.15 : -0.95), z1], normal: [0, 0, 1] });
    }
    if (o.kind === "balance") out.push({ key: "ov:balance", position: [x1 + 0.05, y0 + Number(p.v ?? 0.58) * h, 0], normal: [0, 0, 0] });
    if (o.kind === "dimensions") {
      out.push({ key: "ov:dim-length", position: [x1 + 0.055, y0 + h * 0.5, 0], normal: [0, 0, 0] });
      out.push({ key: "ov:dim-width", position: [0, y1 + 0.05, 0], normal: [0, 0, 0] });
      out.push({ key: "ov:dim-thickness", position: [0.03, y1 + 0.022, (z0 + z1) / 2], normal: [0, 0, 0] });
    }
    if (o.kind === "weight-distribution") out.push({ key: "ov:weight", position: [x0 - 0.05, y0 + h * 0.98, 0], normal: [0, 0, 0] });
  }
  return out;
}

export function Overlays3D({ frame, overlays, active, reducedMotion }: { frame: ModelFrame; overlays: OverlayConfig[]; active: OverlayKind[]; reducedMotion: boolean }) {
  const [x0, y0, z0] = frame.min;
  const [x1, y1, z1] = frame.max;
  const [w, h, d] = frame.size;
  const zFace = z1 - 0.0016;
  const byKind = new Map(overlays.map((o) => [o.kind, o]));
  const on = (k: OverlayKind) => active.includes(k) && byKind.has(k);

  const sweet = byKind.get("sweet-spot")?.params ?? {};
  const impact = byKind.get("impact-zone")?.params ?? {};
  const balance = byKind.get("balance")?.params ?? {};
  const weight = byKind.get("weight-distribution")?.params ?? {};
  const balanceY = y0 + Number(balance.v ?? 0.58) * h;

  const barMat = useMemo(
    () =>
      new THREE.ShaderMaterial({
        vertexShader: zoneVertex,
        fragmentShader: barFragment,
        uniforms: { uCenter: { value: Number(balance.v ?? 0.58) }, uBias: { value: Number(weight.bias ?? 0) } },
        transparent: true,
        depthWrite: false,
        toneMapped: false,
      }),
    [balance.v, weight.bias],
  );
  useEffect(() => () => barMat.dispose(), [barMat]);

  const tick = 0.008;
  return (
    <group>
      {on("impact-zone") && (
        <Zone
          cx={x0 + Number(impact.u ?? 0.5) * w}
          cy={y0 + Number(impact.v ?? 0.6) * h}
          z={zFace}
          rx={Number(impact.ru ?? 0.15) * w}
          ry={Number(impact.rv ?? 0.12) * h}
          color={SERVE}
          fill={0.16}
          dashed
          pulse={false}
        />
      )}
      {on("sweet-spot") && (
        <Zone
          cx={x0 + Number(sweet.u ?? 0.5) * w}
          cy={y0 + Number(sweet.v ?? 0.62) * h}
          z={zFace + 0.0003}
          rx={Number(sweet.ru ?? 0.15) * w}
          ry={Number(sweet.rv ?? 0.1) * h}
          color={BALL}
          fill={0.5}
          dashed={false}
          pulse={!reducedMotion}
        />
      )}
      {on("balance") && (
        <group position={[0, balanceY, 0]}>
          <mesh renderOrder={4}>
            <boxGeometry args={[w * 1.08, 0.0022, d * 1.9]} />
            <meshBasicMaterial color={SERVE} transparent opacity={0.85} toneMapped={false} depthWrite={false} />
          </mesh>
          <mesh position={[x1 + 0.024, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
            <coneGeometry args={[0.009, 0.018, 3]} />
            <meshBasicMaterial color={SERVE} toneMapped={false} />
          </mesh>
          <mesh position={[x0 - 0.024, 0, 0]} rotation={[0, 0, -Math.PI / 2]}>
            <coneGeometry args={[0.009, 0.018, 3]} />
            <meshBasicMaterial color={SERVE} toneMapped={false} />
          </mesh>
        </group>
      )}
      {on("dimensions") && (
        <group>
          <Line points={[[x1 + 0.032, y0, 0], [x1 + 0.032, y1, 0]]} color={LINE} lineWidth={1.4} />
          <Line points={[[x1 + 0.032 - tick, y0, 0], [x1 + 0.032 + tick, y0, 0]]} color={LINE} lineWidth={1.4} />
          <Line points={[[x1 + 0.032 - tick, y1, 0], [x1 + 0.032 + tick, y1, 0]]} color={LINE} lineWidth={1.4} />
          <Line points={[[x0, y1 + 0.028, 0], [x1, y1 + 0.028, 0]]} color={LINE} lineWidth={1.4} />
          <Line points={[[x0, y1 + 0.028 - tick, 0], [x0, y1 + 0.028 + tick, 0]]} color={LINE} lineWidth={1.4} />
          <Line points={[[x1, y1 + 0.028 - tick, 0], [x1, y1 + 0.028 + tick, 0]]} color={LINE} lineWidth={1.4} />
          <Line points={[[0, y1 + 0.012, z0], [0, y1 + 0.012, z1]]} color="#d9f04a" lineWidth={2} />
        </group>
      )}
      {on("weight-distribution") && (
        <mesh position={[x0 - 0.035, (y0 + y1) / 2, 0]} material={barMat} renderOrder={3}>
          <planeGeometry args={[0.014, h]} />
        </mesh>
      )}
    </group>
  );
}
