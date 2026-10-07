import type { Lang, SceneTiming, Timeline } from "../timeline";

/**
 * Every scene gets its own timing. Inside a scene, useCurrentFrame() is 0 at
 * `timing.start`. A scene is mounted for `timing.duration + timeline.overlapFrames`
 * frames: during its first `overlapFrames` it enters ON TOP of the previous scene
 * (so it must start transparent and build up), and during its last `overlapFrames`
 * the next scene enters over it (keep moving, don't freeze). Backgrounds are
 * transparent: the global <Backdrop> sits underneath all scenes.
 */
export type SceneProps = {
  timing: SceneTiming;
  timeline: Timeline;
  lang: Lang;
};
