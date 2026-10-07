"use client";
/**
 * Camera behaviour: real orbit and zoom via camera-controls, animated view
 * presets ("choosing a spec moves the camera"), slow-motion auto-rotation
 * that pauses while the visitor interacts, and synchronised cameras for
 * side-by-side comparison.
 *
 * Replay physics: a flick keeps the racket turning after release and it
 * coasts to rest. How long it coasts comes from the racket's balance and
 * weight (`inertia`), so a head-heavy racket carries more momentum than a
 * light, even-balanced one. On desktop the racket also leans gently toward
 * the mouse pointer while nobody is dragging.
 */
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { useFrame, useThree } from "@react-three/fiber";
import { isPageScrolling, onScrollSettle } from "../scroll-activity";
import { CameraControls } from "@react-three/drei";
import CameraControlsImpl from "camera-controls";
import type { ModelFrame } from "../views";
import { fitDistance, viewPose } from "../views";
import type { SceneProps } from "../types";

const ACTION = CameraControlsImpl.ACTION;
const TAU = Math.PI * 2;

/** Shortest signed angle from a to b. */
function deltaAngle(a: number, b: number): number {
  return ((((b - a) % TAU) + TAU + Math.PI) % TAU) - Math.PI;
}

export function CameraRig({
  frame,
  modelKey,
  command,
  autoRotate,
  reducedMotion,
  interactive,
  wheelZoom,
  initialView,
  sweetV,
  sync,
  inertia = 0.5,
  parallax = false,
  rig,
  onOrbit,
  onUserInteract,
  onFreeView,
  insets,
  lowAngle = false,
  fullscreen = false,
}: {
  frame: ModelFrame;
  sweetV: number;
  /** Open on a low "hero shot" (camera near the turf, racket against the sky). */
  lowAngle?: boolean;
  /** Full screen takes every gesture; on the page, vertical swipes scroll the page. */
  fullscreen?: boolean;
} & Pick<
  SceneProps,
  | "modelKey"
  | "command"
  | "autoRotate"
  | "reducedMotion"
  | "interactive"
  | "wheelZoom"
  | "initialView"
  | "sync"
  | "inertia"
  | "parallax"
  | "rig"
  | "onOrbit"
  | "onUserInteract"
  | "onFreeView"
  | "insets"
>) {
  const ref = useRef<CameraControlsImpl>(null);
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const invalidate = useThree((s) => s.invalidate);
  const gl = useThree((s) => s.gl);
  // Frame the racket inside the part of the canvas the on-screen chrome leaves
  // free (deck, captions, the hero copy), then shift the view so it sits in
  // the middle of that area.
  const it = insets?.top ?? 0;
  const ir = insets?.right ?? 0;
  const ib = insets?.bottom ?? 0;
  const il = insets?.left ?? 0;
  const fit = useMemo(() => {
    const availW = Math.max(80, size.width - il - ir);
    const availH = Math.max(80, size.height - it - ib);
    return fitDistance(frame, camera.fov, availW / availH) * (size.height / availH);
  }, [frame, camera.fov, size.width, size.height, it, ir, ib, il]);
  const focal = useMemo<[number, number]>(() => {
    const worldPerPx = (2 * fit * Math.tan((camera.fov * Math.PI) / 360)) / Math.max(1, size.height);
    // camera-controls: +x moves the camera right (the image shifts left), +y moves it down (the image shifts up).
    return [-((il - ir) / 2) * worldPerPx, -((it - ib) / 2) * worldPerPx];
  }, [fit, camera.fov, size.height, it, ir, ib, il]);
  const fitRef = useRef(fit);
  fitRef.current = fit;
  const userActive = useRef(false);
  const lastInteraction = useRef(0);
  const placedKey = useRef<string | null>(null);
  const animate = !reducedMotion;

  // Momentum state.
  const spin = useRef(0);
  const sample = useRef<{ az: number; t: number; v: number }>({ az: 0, t: 0, v: 0 });
  const lastReported = useRef<number | null>(null);
  const onOrbitRef = useRef(onOrbit);
  onOrbitRef.current = onOrbit;

  // Pointer parallax state (desktop only).
  const pointer = useRef({ x: 0, y: 0, active: false });
  const lean = useRef({ az: 0, polar: 0 });

  // Static configuration.
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    // Kept deliberately simple: the racket always stays centred. Dragging
    // turns it, the tilt is limited so it can never flip over, there is no
    // panning, and zoom stays within a comfortable range.
    c.smoothTime = reducedMotion ? 0 : 0.45;
    c.draggingSmoothTime = reducedMotion ? 0 : 0.1;
    c.minPolarAngle = 1.05;
    c.maxPolarAngle = 1.95;
    c.dollyToCursor = false;
    c.restThreshold = 0.002;
    c.azimuthRotateSpeed = 0.9;
    c.polarRotateSpeed = 0.5;
    c.dollySpeed = 0.6;
    c.touches.one = interactive ? ACTION.TOUCH_ROTATE : ACTION.NONE;
    c.touches.two = interactive ? ACTION.TOUCH_DOLLY : ACTION.NONE;
    c.touches.three = ACTION.NONE;
    c.mouseButtons.left = interactive ? ACTION.ROTATE : ACTION.NONE;
    c.mouseButtons.right = ACTION.NONE;
    c.mouseButtons.middle = interactive ? ACTION.DOLLY : ACTION.NONE;
  }, [interactive, reducedMotion]);

  useEffect(() => {
    const c = ref.current;
    if (c) c.mouseButtons.wheel = interactive && wheelZoom ? ACTION.DOLLY : ACTION.NONE;
  }, [interactive, wheelZoom]);

  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    void c.setFocalOffset(focal[0], focal[1], 0, false);
    invalidate();
  }, [focal, invalidate]);

  // Fit limits and bounds whenever the framing changes.
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    c.minDistance = fit * 0.45;
    c.maxDistance = fit * 1.3;
    const [w, h, d] = frame.size;
    c.setBoundary(new THREE.Box3(new THREE.Vector3(-w * 0.6, -h * 0.6, -d * 3), new THREE.Vector3(w * 0.6, h * 0.6, d * 3)));
  }, [fit, frame]);

  // Initial placement for each racket (not on LOD swaps). If the framing
  // changes before the visitor has touched the camera (the deck appearing, a
  // resize), the opening pose is recomputed so the racket stays framed.
  const placedFit = useRef(0);
  const touched = useRef(false);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const newRacket = placedKey.current !== modelKey;
    const refit = !newRacket && !touched.current && Math.abs(fit - placedFit.current) / fit > 0.02;
    if (!newRacket && !refit) return;
    const pose = viewPose(initialView, frame, fit, sweetV, lowAngle);
    spin.current = 0;
    c.setLookAt(...pose.position, ...pose.target, newRacket && placedKey.current !== null && animate);
    placedKey.current = modelKey;
    placedFit.current = fit;
    if (newRacket) touched.current = false;
    invalidate();
  }, [modelKey, frame, fit, sweetV, initialView, lowAngle, animate, invalidate]);

  // Imperative handle for the replay scrubber.
  useEffect(() => {
    if (!rig) return;
    rig.current = {
      setAzimuth: (azimuth, smooth) => {
        const c = ref.current;
        if (!c) return;
        spin.current = 0;
        touched.current = true;
        lastInteraction.current = performance.now();
        void c.rotateTo(c.azimuthAngle + deltaAngle(c.azimuthAngle, azimuth), c.polarAngle, smooth && animate);
        invalidate();
      },
      stop: () => {
        spin.current = 0;
      },
    };
    return () => {
      rig.current = null;
    };
  }, [rig, animate, invalidate]);

  // One-off commands from the DOM controls.
  useEffect(() => {
    const c = ref.current;
    if (!c || !command) return;
    spin.current = 0;
    touched.current = true;
    switch (command.type) {
      case "view": {
        const pose = viewPose(command.view, frame, fit, sweetV);
        void c.setLookAt(...pose.position, ...pose.target, animate);
        break;
      }
      case "reset": {
        const pose = viewPose(initialView, frame, fit, sweetV, lowAngle);
        void c.setLookAt(...pose.position, ...pose.target, animate);
        break;
      }
      case "zoom":
        void c.dolly(command.step * fit * 0.12, animate);
        break;
      case "rotate":
        void c.rotate(command.azimuth, command.polar, animate);
        break;
    }
    invalidate();
    // Only react to new commands.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [command?.nonce]);

  // Comparison sync: follow other viewers when the visitor moves one of them.
  useEffect(() => {
    if (!sync) return;
    return sync.bus.join(sync.id, (s, what) => {
      const c = ref.current;
      if (!c) return;
      spin.current = 0;
      if (what.rotation) void c.rotateTo(s.azimuth, s.polar, false);
      if (what.zoom) void c.dollyTo(s.distanceRatio * fitRef.current, false);
      invalidate();
    });
  }, [sync, invalidate]);

  // Pointer parallax: track the mouse over the canvas.
  useEffect(() => {
    if (!parallax || reducedMotion) return;
    const el = gl.domElement;
    const move = (e: PointerEvent) => {
      if (e.pointerType !== "mouse") return;
      const r = el.getBoundingClientRect();
      pointer.current.x = Math.max(-1, Math.min(1, ((e.clientX - r.left) / r.width) * 2 - 1));
      pointer.current.y = Math.max(-1, Math.min(1, ((e.clientY - r.top) / r.height) * 2 - 1));
      pointer.current.active = true;
      invalidate();
    };
    const leave = () => {
      pointer.current.active = false;
      invalidate();
    };
    window.addEventListener("pointermove", move, { passive: true });
    document.addEventListener("pointerleave", leave);
    return () => {
      window.removeEventListener("pointermove", move);
      document.removeEventListener("pointerleave", leave);
    };
  }, [parallax, reducedMotion, gl, invalidate]);

  // camera-controls sets touch-action: none on the element it listens to, which stops a
  // vertical swipe over the racket from scrolling the page on phones. On the page, let the
  // browser keep vertical panning (horizontal drags still turn the racket).
  const connected = useThree((s) => s.events.connected) as HTMLElement | undefined;
  useEffect(() => {
    const el = connected ?? gl.domElement;
    el.style.touchAction = fullscreen ? "none" : "pan-y";
  }, [connected, gl, fullscreen]);

  // Hold idle animation while the page scrolls; pick it up again when scrolling settles.
  useEffect(() => onScrollSettle(invalidate), [invalidate]);

  // The render loop runs on demand, so auto-turn needs a nudge to start: when it is
  // switched on, and once the idle pause after an interaction is over.
  const wake = useRef<number | null>(null);
  useEffect(() => {
    invalidate();
    return () => {
      if (wake.current !== null) window.clearTimeout(wake.current);
      wake.current = null;
    };
  }, [autoRotate, reducedMotion, invalidate]);

  useFrame((_, rawDt) => {
    const c = ref.current;
    if (!c) return;
    const dt = Math.min(rawDt, 0.05);
    const scrolling = isPageScrolling();
    const now = performance.now();
    const idle = now - lastInteraction.current > 3500;

    // Coasting spin after a flick.
    if (spin.current !== 0 && !userActive.current) {
      c.azimuthAngle += spin.current * dt;
      const tau = 0.22 + 0.35 * Math.max(0, Math.min(1, inertia));
      spin.current *= Math.exp(-dt / tau);
      if (Math.abs(spin.current) < 0.05) spin.current = 0;
      lastInteraction.current = now;
      invalidate();
    } else if (autoRotate && !reducedMotion && !userActive.current && idle && !scrolling) {
      // Slow-motion replay: a steady quarter-turn every few seconds.
      c.azimuthAngle += dt * 0.22;
      invalidate();
    } else if (autoRotate && !reducedMotion && !userActive.current && !idle && wake.current === null) {
      wake.current = window.setTimeout(
        () => {
          wake.current = null;
          invalidate();
        },
        3500 - (now - lastInteraction.current) + 20,
      );
    }

    // Lean toward the pointer, composed on top of whatever else is turning the camera.
    if (parallax && !reducedMotion && !userActive.current && !scrolling) {
      const targetAz = pointer.current.active ? -pointer.current.x * 0.14 : 0;
      const targetPolar = pointer.current.active ? pointer.current.y * 0.06 : 0;
      const k = 1 - Math.exp(-dt * 3.2);
      const dAz = (targetAz - lean.current.az) * k;
      const dPolar = (targetPolar - lean.current.polar) * k;
      if (Math.abs(dAz) > 1e-5 || Math.abs(dPolar) > 1e-5) {
        lean.current.az += dAz;
        lean.current.polar += dPolar;
        c.azimuthAngle += dAz;
        c.polarAngle += dPolar;
        invalidate();
      }
    }

    // Report the azimuth to the DOM (replay scrubber, lower thirds).
    const az = c.azimuthAngle;
    if (lastReported.current === null || Math.abs(az - lastReported.current) > 0.002) {
      lastReported.current = az;
      onOrbitRef.current?.(az);
    }
  });

  return (
    <CameraControls
      ref={ref}
      makeDefault
      onControlStart={() => {
        const c = ref.current;
        userActive.current = true;
        touched.current = true;
        spin.current = 0;
        lastInteraction.current = performance.now();
        if (c) sample.current = { az: c.azimuthAngle, t: performance.now(), v: 0 };
        onUserInteract?.();
        onFreeView?.();
      }}
      onControl={() => {
        const now = performance.now();
        lastInteraction.current = now;
        const c = ref.current;
        if (!c) return;
        // Smoothed angular velocity of the drag (rad/s).
        const s = sample.current;
        const dtS = (now - s.t) / 1000;
        if (dtS > 0.004) {
          const v = (c.azimuthAngle - s.az) / dtS;
          sample.current = { az: c.azimuthAngle, t: now, v: s.v * 0.55 + v * 0.45 };
        }
        if (sync) sync.bus.publish(sync.id, { azimuth: c.azimuthAngle, polar: c.polarAngle, distanceRatio: c.distance / fitRef.current });
      }}
      onControlEnd={() => {
        userActive.current = false;
        const now = performance.now();
        lastInteraction.current = now;
        // A flick (fast, recent movement) keeps turning; a slow drag stops where it was left.
        const s = sample.current;
        const fresh = now - s.t < 90;
        if (!reducedMotion && fresh && Math.abs(s.v) > 1.6 && !sync) spin.current = Math.max(-7, Math.min(7, s.v * 0.8));
        invalidate();
      }}
    />
  );
}
