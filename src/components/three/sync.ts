/**
 * Camera sync bus for side-by-side comparison. Each viewer joins the bus;
 * when the visitor moves one camera, the others follow (rotation and/or zoom).
 */
export interface CameraState {
  azimuth: number;
  polar: number;
  /** Distance relative to each viewer's own fit distance. */
  distanceRatio: number;
}

type Apply = (s: CameraState, what: { rotation: boolean; zoom: boolean }) => void;

export class SyncBus {
  rotation = true;
  zoom = true;
  private members = new Map<string, Apply>();

  join(id: string, apply: Apply): () => void {
    this.members.set(id, apply);
    return () => this.members.delete(id);
  }

  publish(from: string, state: CameraState) {
    if (!this.rotation && !this.zoom) return;
    for (const [id, apply] of this.members) {
      if (id !== from) apply(state, { rotation: this.rotation, zoom: this.zoom });
    }
  }
}
