"use client";
/**
 * Pins DOM elements ([data-anchor="..."]) to 3D anchor points. Hotspots and
 * overlay labels stay real HTML (focusable buttons, readable text) while
 * following the model on screen. Anchors facing away are marked so CSS can
 * dim them.
 */
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { useFrame, useThree } from "@react-three/fiber";
import type { Anchor } from "../types";

export function Projector({
  anchors,
  center,
  layer,
  version,
}: {
  anchors: Anchor[];
  center: [number, number, number];
  layer: HTMLElement | null;
  version: number;
}) {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const invalidate = useThree((s) => s.invalidate);
  const elements = useRef(new Map<string, HTMLElement>());
  const tmp = useRef({ v: new THREE.Vector3(), n: new THREE.Vector3(), toCam: new THREE.Vector3() });

  useEffect(() => {
    const map = new Map<string, HTMLElement>();
    layer?.querySelectorAll<HTMLElement>("[data-anchor]").forEach((el) => map.set(el.dataset.anchor!, el));
    elements.current = map;
    invalidate();
  }, [layer, version, anchors, invalidate]);

  useFrame(() => {
    const { v, n, toCam } = tmp.current;
    for (const a of anchors) {
      const el = elements.current.get(a.key);
      if (!el) continue;
      v.set(a.position[0] - center[0], a.position[1] - center[1], a.position[2] - center[2]);
      toCam.copy(camera.position).sub(v).normalize();
      n.set(a.normal[0], a.normal[1], a.normal[2]);
      const facing = n.lengthSq() === 0 ? 1 : n.dot(toCam);
      v.project(camera);
      const x = (v.x * 0.5 + 0.5) * size.width;
      const y = (-v.y * 0.5 + 0.5) * size.height;
      el.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`;
      el.dataset.facing = facing > -0.08 ? "front" : "back";
      el.dataset.onscreen = v.z < 1 && x > -30 && y > -30 && x < size.width + 30 && y < size.height + 30 ? "true" : "false";
    }
  });
  return null;
}
