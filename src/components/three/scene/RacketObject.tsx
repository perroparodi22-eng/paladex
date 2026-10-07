"use client";
/**
 * The racket itself: places the loaded glTF scene, animates the exploded
 * "material layers" view by moving named parts (part_* convention), can
 * render as a translucent ghost for overlay comparison, and adds a fine
 * surface-grain normal map on capable devices.
 */
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame, useThree } from "@react-three/fiber";
import type { LoadedModel } from "../model-loader";

/** Exploded-view offsets per part (metres). Parts not listed stay put. */
const EXPLODE: Record<string, [number, number, number]> = {
  part_face_front: [0, 0, 0.07],
  part_print_front: [0, 0, 0.0705],
  part_print: [0, 0, 0.07],
  part_face_back: [0, 0, -0.07],
  part_print_back: [0, 0, -0.0705],
  part_core: [0, 0, 0],
  part_bumper: [0, 0.035, 0],
  part_grip: [0, -0.045, 0.035],
  part_handle: [0, -0.02, 0],
  part_collar: [0, -0.03, 0],
  part_cap: [0, -0.075, 0],
  part_screws: [0, 0, 0],
};

let grainTexture: THREE.Texture | null = null;
function withGrain(m: THREE.MeshStandardMaterial, tex: THREE.Texture) {
  m.normalMap = tex;
  m.normalScale = new THREE.Vector2(0.22, 0.22);
  m.needsUpdate = true;
}

/**
 * Fine grain normal map for the face materials, in two steps so its shader
 * variant compiles in the background: `proxy` holds stand-in meshes with the
 * grain already on (compile these first), `apply` then puts the grain on the
 * real materials, which reuse the compiled program. Null when nothing to do.
 */
export function surfaceGrainPlan(scene: THREE.Object3D): { proxy: THREE.Object3D; apply: () => void } | null {
  const tex = surfaceGrain();
  const targets: THREE.MeshStandardMaterial[] = [];
  const proxy = new THREE.Group();
  scene.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh || !mesh.geometry.getAttribute("uv")) return;
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const m of mats as THREE.MeshStandardMaterial[]) {
      if (!/^face_(print|skin)/.test(m.name) || m.normalMap === tex || targets.includes(m)) continue;
      targets.push(m);
      const stand = m.clone();
      withGrain(stand, tex);
      proxy.add(new THREE.Mesh(mesh.geometry, stand));
    }
  });
  if (!targets.length) return null;
  return { proxy, apply: () => targets.forEach((m) => withGrain(m, tex)) };
}

function surfaceGrain(): THREE.Texture {
  if (grainTexture) return grainTexture;
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const img = ctx.createImageData(size, size);
  // Height field of small raised grains, turned into a tangent-space normal map.
  const h = new Float32Array(size * size);
  for (let i = 0; i < 900; i++) {
    const cx = Math.random() * size;
    const cy = Math.random() * size;
    const r = 1 + Math.random() * 1.6;
    for (let y = Math.floor(cy - r - 1); y <= cy + r + 1; y++)
      for (let x = Math.floor(cx - r - 1); x <= cx + r + 1; x++) {
        const d = Math.hypot(x - cx, y - cy);
        if (d < r) h[((y + size) % size) * size + ((x + size) % size)] += 1 - d / r;
      }
  }
  for (let y = 0; y < size; y++)
    for (let x = 0; x < size; x++) {
      const dx = h[y * size + ((x + 1) % size)] - h[y * size + ((x - 1 + size) % size)];
      const dy = h[((y + 1) % size) * size + x] - h[((y - 1 + size) % size) * size + x];
      const n = new THREE.Vector3(-dx, -dy, 2).normalize();
      const i = (y * size + x) * 4;
      img.data[i] = (n.x * 0.5 + 0.5) * 255;
      img.data[i + 1] = (n.y * 0.5 + 0.5) * 255;
      img.data[i + 2] = (n.z * 0.5 + 0.5) * 255;
      img.data[i + 3] = 255;
    }
  ctx.putImageData(img, 0, 0);
  grainTexture = new THREE.CanvasTexture(canvas);
  grainTexture.wrapS = grainTexture.wrapT = THREE.RepeatWrapping;
  grainTexture.repeat.set(18, 18);
  return grainTexture;
}

export function RacketObject({
  model,
  explode,
  reducedMotion,
  ghost,
  castShadow = false,
}: {
  model: LoadedModel;
  explode: boolean;
  reducedMotion: boolean;
  ghost?: string | null;
  /** Throw a real shadow from the sun onto the court. */
  castShadow?: boolean;
}) {
  const invalidate = useThree((s) => s.invalidate);

  useEffect(() => {
    model.scene.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      mesh.castShadow = castShadow && !ghost;
      mesh.receiveShadow = false;
    });
    invalidate();
  }, [model, castShadow, ghost, invalidate]);
  const amount = useRef(0);
  const parts = useMemo(() => {
    const list: Array<{ object: THREE.Object3D; base: THREE.Vector3; offset: THREE.Vector3 }> = [];
    model.scene.traverse((o) => {
      const off = EXPLODE[o.name];
      if (off) list.push({ object: o, base: o.position.clone(), offset: new THREE.Vector3(...off) });
    });
    return list;
  }, [model]);

  // Ghost styling for overlay comparison.
  useEffect(() => {
    if (!ghost) return;
    const tint = new THREE.Color(ghost);
    model.scene.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const m of mats as THREE.MeshStandardMaterial[]) {
        m.transparent = true;
        m.opacity = 0.34;
        m.depthWrite = false;
        if (m.color) m.color.lerp(tint, 0.65);
        if ("emissive" in m && m.emissive) {
          m.emissive = tint.clone();
          m.emissiveIntensity = 0.25;
        }
        m.needsUpdate = true;
      }
      mesh.renderOrder = 2;
    });
    invalidate();
  }, [ghost, model, invalidate]);

  // Fine grain on the hitting surface is added by the viewer's shader warm-up
  // (surfaceGrainPlan), so it never compiles on screen.

  useEffect(() => {
    if (reducedMotion) {
      amount.current = explode ? 1 : 0;
      for (const p of parts) p.object.position.copy(p.base).addScaledVector(p.offset, amount.current);
    }
    invalidate();
  }, [explode, reducedMotion, parts, invalidate]);

  useFrame((_, dt) => {
    const target = explode ? 1 : 0;
    if (Math.abs(amount.current - target) < 0.0005) return;
    amount.current += (target - amount.current) * (1 - Math.exp(-dt * 7));
    if (Math.abs(amount.current - target) < 0.0005) amount.current = target;
    const e = amount.current;
    for (const p of parts) p.object.position.copy(p.base).addScaledVector(p.offset, e);
    invalidate();
  });

  return <primitive object={model.scene} />;
}
