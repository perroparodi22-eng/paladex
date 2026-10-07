/**
 * Compiles the shader three.js uses to prefilter the studio environment
 * (the PMREM GGX pass) in the background, before the environment is
 * built. Compiled on first use instead, it blocks the main thread for roughly
 * half a second on integrated GPUs, which froze the page while the hero loaded.
 *
 * three.js has no async PMREM API, so this builds the same material through
 * the generator's internals and compiles it with compileAsync. Every step is
 * guarded: if a three.js update renames those internals, this resolves
 * immediately and the environment simply compiles the old (blocking) way.
 */
import * as THREE from "three";

interface PmremInternals {
  _setSize?: (cubeSize: number) => void;
  _allocateTargets?: () => THREE.WebGLRenderTarget;
  _ggxMaterial?: THREE.Material | null;
  dispose: () => void;
}

export async function warmPmremShaders(gl: THREE.WebGLRenderer, cubeSize: number): Promise<void> {
  const pm = new THREE.PMREMGenerator(gl) as unknown as PmremInternals;
  if (typeof pm._setSize !== "function" || typeof pm._allocateTargets !== "function") {
    pm.dispose();
    return;
  }
  let target: THREE.WebGLRenderTarget | null = null;
  try {
    pm._setSize(cubeSize);
    target = pm._allocateTargets();
    // Environments from a cube camera (drei's <Environment>) are prefiltered with the GGX pass only.
    const materials = [pm._ggxMaterial].filter((m): m is THREE.Material => !!m);
    const camera = new THREE.OrthographicCamera();
    // PMREM renders these into render targets; compile under the same state so the
    // program cache keys match (no tone mapping, linear output).
    const previous = gl.getRenderTarget();
    gl.setRenderTarget(target);
    // The stand-in mesh needs a position attribute like PMREM's own meshes: it is part of the cache key.
    const geometry = new THREE.BufferGeometry().setAttribute("position", new THREE.BufferAttribute(new Float32Array(9), 3));
    const pending = materials.map((m) => gl.compileAsync(new THREE.Mesh(geometry, m), camera));
    gl.setRenderTarget(previous);
    await Promise.all(pending);
  } catch {
    // Fall back to compiling on first use.
  } finally {
    target?.dispose();
    // Keep the warmed programs referenced until the real environment has acquired them.
    window.setTimeout(() => pm.dispose(), 15000);
  }
}
