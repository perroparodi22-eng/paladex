/**
 * Racket3DModelLoader: loads .glb/.gltf files with per-request progress,
 * shared caching and the decoders our pipeline uses (Meshopt, Draco, KTX2).
 * Decoders are self-hosted under /decoders (see scripts/copy-decoders.ts).
 *
 * Imported dynamically by the viewer so three.js never lands in the initial
 * page bundle.
 */
import type { Object3D, WebGLRenderer } from "three";
import { GLTFLoader, type GLTF } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { KTX2Loader } from "three/addons/loaders/KTX2Loader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";

export interface LoadedModel {
  url: string;
  scene: Object3D;
  /** Named parts (part_*) present in the model, used by explode/annotations. */
  parts: string[];
  extras: Record<string, unknown>;
}

const cache = new Map<string, Promise<GLTF>>();
let draco: DRACOLoader | null = null;
let ktx2: KTX2Loader | null = null;

function loaderFor(renderer?: WebGLRenderer) {
  const loader = new GLTFLoader();
  loader.setMeshoptDecoder(MeshoptDecoder);
  if (!draco) {
    draco = new DRACOLoader();
    draco.setDecoderPath("/decoders/draco/");
  }
  loader.setDRACOLoader(draco);
  if (renderer) {
    if (!ktx2) {
      ktx2 = new KTX2Loader();
      ktx2.setTranscoderPath("/decoders/basis/");
      ktx2.detectSupport(renderer);
    }
    loader.setKTX2Loader(ktx2);
  }
  return loader;
}

/**
 * Load (or reuse) a model. Progress reports 0–1, or null when the server does
 * not send a content length. Failed loads are evicted so they can be retried.
 */
export function loadGltf(url: string, onProgress?: (fraction: number | null) => void, renderer?: WebGLRenderer): Promise<GLTF> {
  const hit = cache.get(url);
  if (hit) {
    onProgress?.(1);
    return hit;
  }
  const attempt = (r?: WebGLRenderer) =>
    new Promise<GLTF>((resolve, reject) => {
      loaderFor(r).load(
        url,
        (gltf) => resolve(gltf),
        (e) => onProgress?.(e.lengthComputable && e.total > 0 ? e.loaded / e.total : null),
        (err) => reject(err instanceof Error ? err : new Error(String(err))),
      );
    });
  const promise = attempt(renderer).catch(async (err: Error) => {
    // KTX2 (Basis) textures need GPU format detection: retry once with a throwaway renderer.
    if (!renderer && /basisu|KTX2/i.test(err.message)) {
      const { WebGLRenderer } = await import("three");
      const probe = new WebGLRenderer({ canvas: document.createElement("canvas") });
      try {
        return await attempt(probe);
      } finally {
        probe.dispose();
        probe.forceContextLoss();
      }
    }
    throw err;
  });
  cache.set(url, promise);
  promise.catch(() => cache.delete(url));
  return promise;
}

/** A per-viewer copy (materials cloned so overlays and ghosting never leak between viewers). */
export async function loadRacketModel(url: string, onProgress?: (fraction: number | null) => void): Promise<LoadedModel> {
  const gltf = await loadGltf(url, onProgress);
  const scene = gltf.scene.clone(true);
  const parts: string[] = [];
  scene.traverse((o) => {
    if (o.name.startsWith("part_")) parts.push(o.name);
    const mesh = o as unknown as { isMesh?: boolean; material?: { clone(): unknown } | Array<{ clone(): unknown }> };
    if (mesh.isMesh && mesh.material) {
      mesh.material = Array.isArray(mesh.material) ? mesh.material.map((m) => m.clone()) as never : (mesh.material.clone() as never);
    }
  });
  const root = gltf.scene.children[0];
  const extras = ((root?.userData as Record<string, unknown>)?.paladex as Record<string, unknown>) ?? {};
  return { url, scene, parts, extras };
}

/** Warm the HTTP and parse cache for a model the visitor is likely to open next. */
export function preloadModel(url: string) {
  void loadGltf(url).catch(() => {});
}
