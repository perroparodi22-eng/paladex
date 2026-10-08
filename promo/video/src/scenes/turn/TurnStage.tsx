// Scene-local WebGL studio for the "turn" break-out: the site's light rig (same as
// the shared RacketStage) plus a strip light that can sweep across the face, and a
// camera with a lens shift (view offset) so the racket can sit exactly where the
// captured racket sat on screen while the camera still looks straight at it (same
// perspective as the site's viewer). Every value is a prop driven by the scene's
// useCurrentFrame(): nothing animates by itself.
import { Environment, Lightformer } from "@react-three/drei";
import { useLoader, useThree } from "@react-three/fiber";
import { ThreeCanvas } from "@remotion/three";
import React, { useLayoutEffect, useMemo } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { HERO_SLUG, RacketModel, isAudioOnly, modelUrl } from "../../components/Racket3D";

export type Vec3 = [number, number, number];

export type HeroCam = {
  position: Vec3;
  target: Vec3;
  fov: number;
  /** Camera roll (rad). */
  roll: number;
  /** Lens shift in frame px: the image is moved by this much (positive = right / down). */
  shiftX: number;
  shiftY: number;
};

const CamRig: React.FC<{ cam: HeroCam; width: number; height: number }> = ({ cam, width, height }) => {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const { position, target, fov, roll, shiftX, shiftY } = cam;
  useLayoutEffect(() => {
    camera.position.set(...position);
    // Roll around the viewing direction.
    const dir = new THREE.Vector3(target[0] - position[0], target[1] - position[1], target[2] - position[2]).normalize();
    const up = new THREE.Vector3(0, 1, 0).applyAxisAngle(dir, -roll);
    camera.up.copy(up);
    camera.fov = fov;
    camera.near = 0.01;
    camera.far = 60;
    camera.aspect = width / height;
    camera.lookAt(...target);
    camera.setViewOffset(width, height, -shiftX, -shiftY, width, height);
    camera.updateProjectionMatrix();
  }, [camera, position, target, fov, roll, shiftX, shiftY, width, height]);
  return null;
};

const Exposure: React.FC<{ value: number }> = ({ value }) => {
  const gl = useThree((s) => s.gl);
  useLayoutEffect(() => {
    gl.toneMappingExposure = value;
  }, [gl, value]);
  return null;
};

export const TurnStage: React.FC<{
  width: number;
  height: number;
  cam: HeroCam;
  /** Strip light in front of the racket: world x and strength (0 = off). */
  sweepX: number;
  sweep: number;
  exposure?: number;
  children: React.ReactNode;
}> = ({ width, height, cam, sweepX, sweep, exposure = 1.05, children }) =>
  isAudioOnly() ? null : (
  <ThreeCanvas
    width={width}
    height={height}
    dpr={1}
    gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: "high-performance" }}
    camera={{ fov: cam.fov, near: 0.01, far: 60, position: cam.position }}
    onCreated={({ gl }) => {
      gl.toneMapping = THREE.NeutralToneMapping;
      gl.outputColorSpace = THREE.SRGBColorSpace;
      gl.toneMappingExposure = exposure;
      gl.setClearColor(0x000000, 0);
    }}
  >
    <Exposure value={exposure} />
    <CamRig cam={cam} width={width} height={height} />
    {/* The site's studio rig (src/components/three/scene/Stage.tsx), plus the sweep. */}
    <Environment resolution={256} frames={1}>
      <Lightformer form="rect" intensity={2.2} color="#ffffff" scale={[6, 3, 1]} position={[0, 4, 1]} rotation-x={Math.PI / 2} />
      <Lightformer form="rect" intensity={3} color="#e8eefc" scale={[0.6, 5, 1]} position={[-3, 1, -1.5]} rotation-y={Math.PI / 3} />
      <Lightformer form="rect" intensity={2.4} color="#fff6ee" scale={[0.6, 5, 1]} position={[3, 1, -1.5]} rotation-y={-Math.PI / 3} />
      <Lightformer form="rect" intensity={0.5} color="#ffffff" scale={[4, 2, 1]} position={[0, 0.5, 3.5]} />
      <Lightformer form="rect" intensity={5 * sweep} color="#ffffff" scale={[0.45, 6, 1]} position={[sweepX, 0.6, 2.4]} />
    </Environment>
    <directionalLight position={[0.8, 3.2, 2.2]} intensity={2.2} color="#ffffff" />
    <directionalLight position={[-2.4, 1.2, -2]} intensity={2.4} color="#dfe7ff" />
    <directionalLight position={[2.4, 1, -2]} intensity={2.4 * 0.7} color="#fff1e4" />
    <directionalLight position={[0, 0.4, 3]} intensity={0.55} />
    <hemisphereLight args={["#d9dde6", "#0b0c0e", 0.45]} />
    {children}
  </ThreeCanvas>
);

/** Model-space height (0 butt … 1 tip) of this racket's sweet spot (site data: sweetSpotV). */
const SWEET_V = 0.67;

/**
 * The hero racket, centred like <RacketModel>, turned by `yaw`/`pitch` (yaw first,
 * then pitch, both in world axes: the same as the site's orbit camera at
 * azimuth -yaw, polar π/2 - pitch). `ring` 0–1 draws the faint ball-lime
 * sweet-spot ring on the BACK face (the face the site shows after "Back").
 */
export const HeroRacket: React.FC<{ yaw: number; pitch: number; roll?: number; ring: number; ringScale?: number }> = ({ yaw, pitch, roll = 0, ring, ringScale = 1 }) => {
  const gltf = useLoader(GLTFLoader, modelUrl(HERO_SLUG), (loader) => {
    (loader as GLTFLoader).setMeshoptDecoder(MeshoptDecoder);
  });
  // Where the ring goes, in the centred frame RacketModel uses.
  const geo = useMemo(() => {
    const box = new THREE.Box3().setFromObject(gltf.scene);
    const c = box.getCenter(new THREE.Vector3());
    const h = box.max.y - box.min.y;
    const y = box.min.y + SWEET_V * h - c.y;
    // Back face: the face mesh nearest -Z (a hair in front of it).
    let faceZ = box.min.z - c.z;
    gltf.scene.traverse((o) => {
      if (o.name === "part_face_back") {
        const b = new THREE.Box3().setFromObject(o);
        faceZ = b.min.z - c.z;
      }
    });
    return { y, z: faceZ - 0.0012, w: box.max.x - box.min.x };
  }, [gltf]);
  const r = geo.w * 0.2;
  return (
    <group rotation={[pitch, yaw, roll]}>
      <RacketModel slug={HERO_SLUG} />
      {ring > 0.001 && (
        <group position={[0, geo.y, geo.z]} rotation={[0, Math.PI, 0]} scale={ringScale}>
          {/* thin ring */}
          <mesh renderOrder={2}>
            <ringGeometry args={[r * 0.972, r, 160]} />
            <meshBasicMaterial color="#d9f04a" transparent opacity={0.6 * ring} toneMapped={false} depthWrite={false} side={THREE.DoubleSide} />
          </mesh>
          {/* faint inner wash */}
          <mesh renderOrder={1}>
            <circleGeometry args={[r * 0.972, 160]} />
            <meshBasicMaterial color="#d9f04a" transparent opacity={0.05 * ring} toneMapped={false} depthWrite={false} side={THREE.DoubleSide} />
          </mesh>
        </group>
      )}
    </group>
  );
};
