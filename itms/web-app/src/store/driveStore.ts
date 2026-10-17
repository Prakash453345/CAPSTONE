import { create } from "zustand";

/**
 * A responder's own settings for the Drive page: which unit they are driving,
 * whether guidance is spoken, and whether the map follows them. The unit and
 * voice choice survive a reload (an ambulance crew should not have to set them
 * again mid-shift); the camera mode is per visit.
 */
const KEY = "traffix.drive";

interface Saved {
  unitId: string | null;
  voice: boolean;
}

function read(): Saved {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "null") as Partial<Saved> | null;
    return { unitId: typeof raw?.unitId === "string" ? raw.unitId : null, voice: raw?.voice !== false };
  } catch {
    return { unitId: null, voice: true };
  }
}

function write(saved: Saved) {
  try {
    localStorage.setItem(KEY, JSON.stringify(saved));
  } catch {
    // storage blocked: the choice just won't be remembered
  }
}

export type CameraMode = "follow" | "free";

interface DriveState extends Saved {
  camera: CameraMode;
  setUnit: (unitId: string | null) => void;
  setVoice: (voice: boolean) => void;
  setCamera: (camera: CameraMode) => void;
}

export const useDriveStore = create<DriveState>((set, get) => ({
  ...read(),
  camera: "follow",
  setUnit: (unitId) => {
    set({ unitId, camera: "follow" });
    write({ unitId, voice: get().voice });
  },
  setVoice: (voice) => {
    set({ voice });
    write({ unitId: get().unitId, voice });
  },
  setCamera: (camera) => set({ camera }),
}));
