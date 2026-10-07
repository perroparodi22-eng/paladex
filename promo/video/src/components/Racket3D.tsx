// Real Paladex racket models (the same .glb files the site serves) rendered with
// the site's "black studio" light rig. Every transform is a prop, so scenes drive
// all motion from useCurrentFrame() (Remotion rule: no useFrame, nothing animates
// by itself).
import { ContactShadows, Environment, Lightformer } from "@react-three/drei";
import { useLoader, useThree } from "@react-three/fiber";
import { ThreeCanvas } from "@remotion/three";
import React, { useLayoutEffect, useMemo } from "react";
import { staticFile } from "remotion";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

/** Slugs with a traced 3D model in public/models (copied from the site). */
export const HERO_SLUG = "nox-at10-luxury-genius-18k-alum";
export const modelUrl = (slug: string) => staticFile(`models/${slug}.glb`);

type Vec3 = [number, number, number];

/**
 * A full-frame transparent WebGL layer with the studio lights. Put one or more
 * <RacketModel/> inside. The camera looks down -Z from `cameraPosition`.
 */
export const RacketStage: React.FC<{
  width: number;
  height: number;
  children: React.ReactNode;
  cameraPosition?: Vec3;
  cameraTarget?: Vec3;
  fov?: number;
  exposure?: number;
  /** Soft contact shadow on an invisible floor at this height (metres), or null. */
  floorY?: number | null;
  style?: React.CSSProperties;
}> = ({ width, height, children, cameraPosition = [0, 0, 1.4], cameraTarget = [0, 0, 0], fov = 30, exposure = 1.05, floorY = null, style }) => {
  return (
    <ThreeCanvas
      width={width}
      height={height}
      style={style}
      dpr={1}
      gl={{ antialias: true, alpha: true, preserveDrawingBuffer: true, powerPreference: "high-performance" }}
      camera={{ fov, near: 0.01, far: 80, position: cameraPosition }}
      onCreated={({ gl }) => {
        gl.toneMapping = THREE.NeutralToneMapping;
        gl.outputColorSpace = THREE.SRGBColorSpace;
        gl.toneMappingExposure = exposure;
        gl.setClearColor(0x000000, 0);
      }}
    >
      <CameraRig position={cameraPosition} target={cameraTarget} fov={fov} />
      <StudioLights />
      {floorY !== null && (
        <ContactShadows position={[0, floorY, 0]} scale={2.2} blur={2.8} far={1.2} opacity={0.85} frames={1} resolution={512} color="#000000" />
      )}
      {children}
    </ThreeCanvas>
  );
};

/** Keeps the camera in sync with props on every frame. */
const CameraRig: React.FC<{ position: Vec3; target: Vec3; fov: number }> = ({ position, target, fov }) => {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  useLayoutEffect(() => {
    camera.position.set(...position);
    camera.fov = fov;
    camera.lookAt(...target);
    camera.updateProjectionMatrix();
  }, [camera, position, target, fov]);
  return null;
};

/** The site's light rig (src/components/three/scene/Stage.tsx, dark palette). */
export const StudioLights: React.FC = () => (
  <>
    <Environment resolution={256} frames={1}>
      <Lightformer form="rect" intensity={2.2} color="#ffffff" scale={[6, 3, 1]} position={[0, 4, 1]} rotation-x={Math.PI / 2} />
      <Lightformer form="rect" intensity={3} color="#e8eefc" scale={[0.6, 5, 1]} position={[-3, 1, -1.5]} rotation-y={Math.PI / 3} />
      <Lightformer form="rect" intensity={2.4} color="#fff6ee" scale={[0.6, 5, 1]} position={[3, 1, -1.5]} rotation-y={-Math.PI / 3} />
      <Lightformer form="rect" intensity={0.5} color="#ffffff" scale={[4, 2, 1]} position={[0, 0.5, 3.5]} />
    </Environment>
    <directionalLight position={[0.8, 3.2, 2.2]} intensity={2.2} color="#ffffff" />
    <directionalLight position={[-2.4, 1.2, -2]} intensity={2.4} color="#dfe7ff" />
    <directionalLight position={[2.4, 1, -2]} intensity={2.4 * 0.7} color="#fff1e4" />
    <directionalLight position={[0, 0.4, 3]} intensity={0.55} />
    <hemisphereLight args={["#d9dde6", "#0b0c0e", 0.45]} />
  </>
);

/**
 * One racket, centred on its bounding box (the model's origin is arbitrary).
 * Rotation is in radians, Euler XYZ. Height of a racket is ~0.46 m.
 */
export const RacketModel: React.FC<{
  slug: string;
  position?: Vec3;
  rotation?: Vec3;
  /** Uniform, or per axis (e.g. [1, 1, 0.02] squashes the racket flat). */
  scale?: number | Vec3;
  /** 0–1. Below 1 the materials turn transparent (for fades). */
  opacity?: number;
}> = ({ slug, position = [0, 0, 0], rotation = [0, 0, 0], scale = 1, opacity = 1 }) => {
  const gltf = useLoader(GLTFLoader, modelUrl(slug), (loader) => {
    (loader as GLTFLoader).setMeshoptDecoder(MeshoptDecoder);
  });
  const { object, center } = useMemo(() => {
    const object = gltf.scene.clone(true);
    // Own materials per instance so opacity can differ between clones.
    object.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.isMesh) {
        mesh.material = Array.isArray(mesh.material) ? mesh.material.map((m) => m.clone()) : mesh.material.clone();
      }
    });
    const box = new THREE.Box3().setFromObject(object);
    const center = box.getCenter(new THREE.Vector3());
    return { object, center };
  }, [gltf]);

  useLayoutEffect(() => {
    object.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const m of mats) {
        const fade = opacity < 0.999;
        if (m.transparent !== fade) m.needsUpdate = true;
        m.transparent = fade;
        m.opacity = opacity;
        m.depthWrite = !fade;
      }
    });
  }, [object, opacity]);

  return (
    <group position={position} rotation={rotation} scale={scale} visible={opacity > 0.001}>
      <primitive object={object} position={[-center.x, -center.y, -center.z]} />
    </group>
  );
};
