/**
 * WebGL capability detection (cached). Testing aids:
 *   ?webgl=0                        force the no-WebGL fallback
 *   localStorage paladex:no-webgl=1  same, persistent
 */
let cached: boolean | null = null;

export function hasWebGL(): boolean {
  if (cached !== null) return cached;
  if (typeof window === "undefined") return false;
  try {
    const params = new URLSearchParams(window.location.search);
    if (params.get("webgl") === "0") return (cached = false);
    if (window.localStorage?.getItem("paladex:no-webgl") === "1") return (cached = false);
  } catch {
    // Storage can be blocked; ignore.
  }
  try {
    const canvas = document.createElement("canvas");
    const gl = (canvas.getContext("webgl2") || canvas.getContext("webgl")) as WebGLRenderingContext | null;
    cached = !!gl;
    gl?.getExtension("WEBGL_lose_context")?.loseContext();
  } catch {
    cached = false;
  }
  return cached;
}

/** Debug aid: ?model=broken makes the viewer request a missing file to exercise the error state. */
export function forcedModelFailure(): boolean {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).get("model") === "broken";
}
