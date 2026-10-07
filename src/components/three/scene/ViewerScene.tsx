"use client";
/**
 * The WebGL canvas for one viewer. Loaded lazily (next/dynamic, ssr: false)
 * so three.js only downloads when a visitor actually opens a 3D view.
 * Renders on demand: no frames are drawn while nothing moves.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { PerformanceMonitor } from "@react-three/drei";
import type { SceneProps, Anchor } from "../types";
import type { LoadedModel } from "../model-loader";
import type { ModelFrame } from "../views";
import { Stage, paletteFor } from "./Stage";
import { RacketObject, surfaceGrainPlan } from "./RacketObject";
import { CameraRig } from "./CameraRig";
import { Overlays3D, overlayAnchors } from "./Overlays3D";
import { Projector } from "./Projector";
import { warmPmremShaders } from "./pmrem-warmup";

/** Compiles the environment's prefilter shaders off the main thread, then reports ready. */
function EnvWarm({ size, onReady }: { size: number; onReady: () => void }) {
  const gl = useThree((s) => s.gl);
  const ready = useRef(onReady);
  ready.current = onReady;
  useEffect(() => {
    let alive = true;
    void warmPmremShaders(gl, size).then(() => alive && ready.current());
    return () => {
      alive = false;
    };
  }, [gl, size]);
  return null;
}

function frameOf(object: THREE.Object3D): ModelFrame {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  return {
    min: box.min.toArray() as [number, number, number],
    max: box.max.toArray() as [number, number, number],
    size: size.toArray() as [number, number, number],
    center: center.toArray() as [number, number, number],
  };
}

/** Outward normal for a normalised anchor position (front/back/sides/top). */
function anchorNormal(u: number, v: number, w: number): [number, number, number] {
  if (w >= 0.9) return [0, 0, 1];
  if (w <= 0.1) return [0, 0, -1];
  if (v >= 0.97) return [0, 1, 0];
  if (u >= 0.85) return [1, 0, 0];
  if (u <= 0.15) return [-1, 0, 0];
  return [0, 0, 0];
}

/**
 * Compiles a model's shaders in the background (KHR_parallel_shader_compile via
 * compileAsync) before it is first drawn. Compiling on first draw instead blocks
 * the main thread for 100-200 ms per material, which froze scrolling while the
 * page loaded. The previous model stays on stage until the next one is ready.
 */
function WarmModel({
  model,
  grain,
  onReady,
  children,
}: {
  model: LoadedModel;
  grain: boolean;
  onReady: () => void;
  children: (model: LoadedModel) => ReactNode;
}) {
  const gl = useThree((s) => s.gl);
  const camera = useThree((s) => s.camera);
  const scene = useThree((s) => s.scene);
  const invalidate = useThree((s) => s.invalidate);
  const [shown, setShown] = useState<LoadedModel | null>(null);
  const ready = useRef(onReady);
  ready.current = onReady;
  useEffect(() => {
    let alive = true;
    // Grain (high-quality devices) is compiled on stand-in meshes, then applied.
    const grainPlan = grain ? surfaceGrainPlan(model.scene) : null;
    Promise.all([gl.compileAsync(model.scene, camera, scene), grainPlan && gl.compileAsync(grainPlan.proxy, camera, scene)])
      .catch(() => undefined)
      .then(() => {
        if (!alive) return;
        grainPlan?.apply();
        setShown(model);
        ready.current();
        invalidate();
      });
    return () => {
      alive = false;
    };
  }, [model, grain, gl, camera, scene, invalidate]);
  return shown ? children(shown) : null;
}

function ContextWatcher({ onLost, onFirstFrame, armed }: { onLost?: () => void; onFirstFrame?: () => void; armed: boolean }) {
  const gl = useThree((s) => s.gl);
  const callbacks = useRef({ onLost, onFirstFrame });
  callbacks.current = { onLost, onFirstFrame };
  const fired = useRef(false);
  useEffect(() => {
    const el = gl.domElement;
    const lost = (e: Event) => {
      e.preventDefault();
      callbacks.current.onLost?.();
    };
    el.addEventListener("webglcontextlost", lost);
    return () => el.removeEventListener("webglcontextlost", lost);
  }, [gl]);
  // Fires once the first frame with the racket in it has actually been drawn.
  useFrame(() => {
    if (fired.current || !armed) return;
    fired.current = true;
    requestAnimationFrame(() => {
      callbacks.current.onFirstFrame?.();
    });
  });
  return null;
}

/** Keeps tone-mapping exposure in step with the lighting preset. */
function Exposure({ value }: { value: number }) {
  const gl = useThree((s) => s.gl);
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => {
    gl.toneMappingExposure = value;
    invalidate();
  }, [gl, value, invalidate]);
  return null;
}

export default function ViewerScene(props: SceneProps) {
  const { model, quality } = props;
  const [dpr, setDpr] = useState<number>(Math.min(quality.dpr[1], typeof window !== "undefined" ? window.devicePixelRatio : 1));

  // Frame from the first model of this racket (stable across preview -> full swaps).
  const frame = useMemo(() => frameOf(model.scene), [props.modelKey]); // eslint-disable-line react-hooks/exhaustive-deps
  const center = frame.center;
  const sweet = props.overlays.find((o) => o.kind === "sweet-spot");
  const sweetV = Number(sweet?.params.v ?? 0.66);

  const anchors = useMemo<Anchor[]>(() => {
    const [x0, y0, z0] = frame.min;
    const [w, h, d] = frame.size;
    const hs = props.hotspots.map((hp) => ({
      key: `hs:${hp.key}`,
      position: [x0 + hp.u * w, y0 + hp.v * h, z0 + hp.w * d] as [number, number, number],
      normal: anchorNormal(hp.u, hp.v, hp.w),
    }));
    return [...hs, ...overlayAnchors(frame, props.overlays, props.activeOverlays)];
  }, [frame, props.hotspots, props.overlays, props.activeOverlays]);

  const ghostOffset = useMemo<[number, number, number] | null>(() => {
    if (!props.ghost) return null;
    const g = frameOf(props.ghost.model.scene);
    // Align both rackets at the butt cap and on the centre line.
    return [-g.center[0], -center[1] + (frame.min[1] - g.min[1]), -g.center[2]];
  }, [props.ghost, frame, center]);

  const floorY = -frame.size[1] / 2 - 0.035;
  const palette = useMemo(() => paletteFor(props.lighting), [props.lighting]);
  // Which model's shaders are compiled and on stage (the contact shadow is drawn once it is).
  const [warmUrl, setWarmUrl] = useState<string | null>(null);
  // The environment (and so the racket's final shaders) waits for its prefilter shaders.
  const [envReady, setEnvReady] = useState(false);

  return (
    <Canvas
      frameloop="demand"
      dpr={dpr}
      gl={{ antialias: quality.antialias, alpha: true, powerPreference: "high-performance", preserveDrawingBuffer: false }}
      camera={{ fov: 30, near: 0.01, far: 60, position: [0, 0, 1.4] }}
      onCreated={({ gl }) => {
        // Neutral keeps the court blue blue (ACES drifts saturated blues toward purple).
        gl.toneMapping = THREE.NeutralToneMapping;
        gl.outputColorSpace = THREE.SRGBColorSpace;
      }}
      style={{ touchAction: props.fullscreen ? "none" : "pan-y" }}
      aria-hidden="true"
      tabIndex={-1}
    >
      <PerformanceMonitor onDecline={() => setDpr(1)} />
      <ContextWatcher onLost={props.onContextLost} onFirstFrame={props.onFirstFrame} armed={warmUrl !== null} />
      <Exposure value={palette.exposure} />
      {!envReady && <EnvWarm size={quality.envResolution} onReady={() => setEnvReady(true)} />}
      <Stage envReady={envReady} preset={props.lighting} palette={palette} quality={quality} stage={props.stage} floorY={floorY} extent={frame.size[1]} shadowKey={warmUrl ?? "warming"} />
      <group position={[-center[0], -center[1], -center[2]]}>
        {envReady && (
          <WarmModel model={model} grain={!!props.surfaceGrain && !props.ghostColor} onReady={() => setWarmUrl(model.url)}>
            {(m) => <RacketObject model={m} explode={props.explode} reducedMotion={props.reducedMotion} ghost={props.ghostColor ?? null} />}
          </WarmModel>
        )}
        <Overlays3D frame={frame} overlays={props.overlays} active={props.activeOverlays} reducedMotion={props.reducedMotion} />
      </group>
      {props.ghost && ghostOffset && (
        <group position={ghostOffset}>
          <RacketObject model={props.ghost.model} explode={false} reducedMotion={props.reducedMotion} ghost={props.ghost.color} />
        </group>
      )}
      <CameraRig
        frame={frame}
        sweetV={sweetV}
        modelKey={props.modelKey}
        command={props.command}
        autoRotate={props.autoRotate}
        reducedMotion={props.reducedMotion}
        interactive={props.interactive}
        wheelZoom={props.wheelZoom}
        fullscreen={props.fullscreen}
        initialView={props.initialView}
        sync={props.sync}
        inertia={props.inertia}
        parallax={props.parallax}
        rig={props.rig}
        onOrbit={props.onOrbit}
        insets={props.insets}
        lowAngle={props.lowAngle}
        onUserInteract={props.onUserInteract}
        onFreeView={props.onFreeView}
      />
      <Projector anchors={anchors} center={center} layer={props.anchorLayer} version={props.anchorVersion} />
    </Canvas>
  );
}
