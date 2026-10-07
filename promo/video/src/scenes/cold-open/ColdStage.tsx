// Scene-local WebGL studio for the cold open. Same light rig as the shared
// RacketStage (the site's black studio), but every light is a prop so the scene
// can reveal it gradually: rim lights first (tracing the silhouette), then the
// key light and fill, plus one moving strip light for a reflection sweep.
// Everything is driven from useCurrentFrame() by the caller: no useFrame.
import { Environment, Lightformer } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { ThreeCanvas } from "@remotion/three";
import React, { useLayoutEffect } from "react";
import * as THREE from "three";
import { isAudioOnly } from "../../components/Racket3D";

export type Vec3 = [number, number, number];

export type LightRig = {
  /** Rim strength of the two back directional lights (1 = the site's rig; boosted during the reveal). */
  rim: number;
  /** Strength of the back strip lights in the reflections (1 = the site's rig). */
  rimEnv: number;
  /** 0..1: rim lights travel from high above the racket down to its sides. */
  rimTravel: number;
  /** Camera azimuth (rad): the rim lights stay behind the racket as seen from the camera. */
  camAz: number;
  /** 0..1 key light from above/front (soft box + directional). */
  key: number;
  /** 0..1 front fill + hemisphere. */
  fill: number;
  /** Soft panel straight behind the racket (reflections only): it lights the glossy outline. */
  back: number;
  /** Strip light passing in front of the racket: x position (world) and strength. */
  sweepX: number;
  sweep: number;
  exposure: number;
};

const Exposure: React.FC<{ value: number }> = ({ value }) => {
  const gl = useThree((s) => s.gl);
  useLayoutEffect(() => {
    gl.toneMappingExposure = value;
  }, [gl, value]);
  return null;
};

const CameraRig: React.FC<{ position: Vec3; target: Vec3; fov: number; roll: number }> = ({ position, target, fov, roll }) => {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  useLayoutEffect(() => {
    camera.position.set(...position);
    camera.up.set(Math.sin(roll), Math.cos(roll), 0);
    camera.fov = fov;
    camera.lookAt(...target);
    camera.updateProjectionMatrix();
  }, [camera, position, target, fov, roll]);
  return null;
};

/**
 * A light behind the racket as seen from the camera: `side` -1 left / +1 right,
 * `away` = angle from the camera direction (180° = straight behind), `elev` = height.
 */
const behind = (side: number, awayDeg: number, elevDeg: number, camAz: number, r = 3.2): Vec3 => {
  const a = (awayDeg * Math.PI) / 180;
  const e = (elevDeg * Math.PI) / 180;
  const x = side * Math.sin(a) * Math.cos(e);
  const z = Math.cos(a) * Math.cos(e);
  const y = Math.sin(e);
  return [(x * Math.cos(camAz) + z * Math.sin(camAz)) * r, y * r, (-x * Math.sin(camAz) + z * Math.cos(camAz)) * r];
};

export const ColdStage: React.FC<{
  width: number;
  height: number;
  camera: { position: Vec3; target: Vec3; fov: number; roll: number };
  rig: LightRig;
  children: React.ReactNode;
}> = ({ width, height, camera, rig, children }) => {
  if (isAudioOnly()) return null;
  const { rim, rimEnv, rimTravel, camAz, key, fill, back, sweepX, sweep, exposure } = rig;
  // Rim lights start high above the head and travel down both sides, so the
  // highlight runs along the frame like a pen tracing the outline.
  const elev = 74 - 60 * rimTravel;
  const left = behind(-1, 122, elev, camAz);
  const right = behind(1, 126, elev, camAz);
  // The back panel descends from high behind the head to straight behind it, so its
  // reflection runs from the top of the frame down both sides.
  const backPos = behind(0, 170, 62 - 54 * rimTravel, camAz, 3);
  return (
    <ThreeCanvas
      width={width}
      height={height}
      dpr={1}
      gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: "high-performance" }}
      camera={{ fov: camera.fov, near: 0.01, far: 80, position: camera.position }}
      onCreated={({ gl }) => {
        gl.toneMapping = THREE.NeutralToneMapping;
        gl.outputColorSpace = THREE.SRGBColorSpace;
        gl.toneMappingExposure = exposure;
        gl.setClearColor(0x000000, 0);
      }}
    >
      <Exposure value={exposure} />
      <CameraRig {...camera} />
      {/* Reflections (re-captured every frame because the children change). */}
      <Environment resolution={256} frames={1}>
        <Lightformer form="rect" intensity={2.2 * key} color="#ffffff" scale={[6, 3, 1]} position={[0, 4, 1]} rotation-x={Math.PI / 2} />
        <Lightformer form="rect" intensity={3 * rimEnv} color="#e8eefc" scale={[0.6, 5, 1]} position={[-3, 1, -1.5]} rotation-y={Math.PI / 3} />
        <Lightformer form="rect" intensity={2.4 * rimEnv} color="#fff6ee" scale={[0.6, 5, 1]} position={[3, 1, -1.5]} rotation-y={-Math.PI / 3} />
        <Lightformer form="rect" intensity={0.5 * fill} color="#ffffff" scale={[4, 2, 1]} position={[0, 0.5, 3.5]} />
        <Lightformer form="rect" intensity={5 * sweep} color="#ffffff" scale={[0.5, 6, 1]} position={[sweepX, 0.6, 2.6]} />
        {back > 0.001 && <Lightformer form="rect" intensity={back} color="#e9eef8" scale={[2.4, 1.4, 1]} position={backPos} />}
      </Environment>
      {/* Key from above and slightly in front. */}
      <directionalLight position={[0.8, 3.2, 2.2]} intensity={2.2 * key} color="#ffffff" />
      {/* Rim lights behind the racket trace its silhouette. */}
      <directionalLight position={left} intensity={2.4 * rim} color="#dfe7ff" />
      <directionalLight position={right} intensity={2.4 * 0.7 * rim} color="#fff1e4" />
      {/* Soft front fill so the face never drops to black once lit. */}
      <directionalLight position={[0, 0.4, 3]} intensity={0.55 * fill} />
      <hemisphereLight color="#d9dde6" groundColor="#0b0c0e" intensity={0.45 * fill} />
      {children}
    </ThreeCanvas>
  );
};
