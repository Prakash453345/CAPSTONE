import { create } from "zustand";

/**
 * A responder's own settings for the crew page: which unit they are driving,
 * whether guidance is spoken, and whether the map follows them. The unit and
 * voice choice survive a reload (an ambulance crew should not have to set them
 * again mid-shift); the camera mode is per visit.
 */
const KEY = "traffix.crew";

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

/** A call offered to one crew, straight off `crew.offer`. */
export interface CrewOffer {
  offerId: string;
  incidentId: string;
  unitId: string;
  kind: string;
  edgeId: string;
  etaS: number;
  /** Browser clock, so the card can count down without trusting sim time. */
  expiresAtMs: number;
}

/** Seconds a crew has to answer, mirrored from DEFAULT_OFFER_TIMEOUT_S in
 *  `live/crew_dispatch.py`. The server is the authority -- a late accept is
 *  rejected there -- so this only drives the countdown. */
const OFFER_SECONDS = 25;

/** One unit of the fleet as the dispatcher sees it (`CrewRosterUpdated`).
 *  Its position is simulated: the depot while idle, its SUMO vehicle's road
 *  while driving -- the stand-in for a phone's GPS. */
export interface FleetUnit {
  unitId: string;
  kind: "ambulance" | "police" | "fire_truck" | string;
  callSign: string;
  crew: string | null;
  onDuty: boolean;
  busy: boolean;
  edgeId: string;
  /** [lng, lat], when the unit has a known road. */
  at: [number, number] | null;
}

export interface HospitalOption {
  facilityId: string;
  name: string;
  edgeId: string;
  etaS: number;
  at: [number, number] | null;
}

/** An ambulance's patient leg (`CrewHospitalOptions`): offered at the scene,
 *  then driving to the chosen hospital, then done. */
export interface HospitalMission {
  unitId: string;
  requestId: string;
  sceneEdge: string;
  state: "at_scene" | "to_hospital" | "done";
  recommendedId: string;
  chosenId: string;
  options: HospitalOption[];
}

/** Where a call stands before it becomes a request, for the console: who it
 *  is offered to, who already said no, or that nobody took it. */
export interface CallStatus {
  incidentId: string;
  kind: string;
  state: "offered" | "accepted" | "declined" | "expired" | "withdrawn" | "exhausted";
  unitId: string;
  etaS: number;
  asked: string[];
  atMs: number;
}

const toLngLat = (lat: unknown, lon: unknown): [number, number] | null =>
  typeof lat === "number" && typeof lon === "number" ? [lon, lat] : null;

interface CrewState extends Saved {
  camera: CameraMode;
  /** Open offers by unit id. One per unit: the dispatcher never has two calls
   *  out to the same crew at once. */
  offers: Record<string, CrewOffer>;
  fleet: FleetUnit[];
  hospital: Record<string, HospitalMission>;
  calls: Record<string, CallStatus>;
  applyFleet: (payload: Record<string, unknown>) => void;
  applyHospital: (payload: Record<string, unknown>) => void;
  setUnit: (unitId: string | null) => void;
  setVoice: (voice: boolean) => void;
  setCamera: (camera: CameraMode) => void;
  /** Apply one `CrewOfferUpdated` payload. Anything that is not an open offer
   *  -- accepted, declined, expired, withdrawn, exhausted -- clears it, so the
   *  card disappears the moment the call stops being this crew's to take. */
  applyOffer: (payload: Record<string, unknown>) => void;
  clearOffer: (unitId: string) => void;
}

export const useCrewStore = create<CrewState>((set, get) => ({
  ...read(),
  camera: "follow",
  offers: {},
  fleet: [],
  hospital: {},
  calls: {},
  setUnit: (unitId) => {
    set({ unitId, camera: "follow" });
    write({ unitId, voice: get().voice });
  },
  setVoice: (voice) => {
    set({ voice });
    write({ unitId: get().unitId, voice });
  },
  setCamera: (camera) => set({ camera }),

  applyFleet: (payload) => {
    const units = Array.isArray(payload.units) ? (payload.units as Record<string, unknown>[]) : [];
    set({
      fleet: units.map((u) => ({
        unitId: String(u.unit_id ?? ""),
        kind: String(u.kind ?? ""),
        callSign: String(u.call_sign || u.unit_id || ""),
        crew: u.crew == null ? null : String(u.crew),
        onDuty: u.on_duty === true,
        busy: u.busy === true,
        edgeId: String(u.edge_id ?? ""),
        at: toLngLat(u.lat, u.lon),
      })),
    });
  },

  applyHospital: (payload) => {
    const unitId = String(payload.unit_id ?? "");
    if (!unitId) return;
    const options = Array.isArray(payload.options) ? (payload.options as Record<string, unknown>[]) : [];
    set({
      hospital: {
        ...get().hospital,
        [unitId]: {
          unitId,
          requestId: String(payload.request_id ?? ""),
          sceneEdge: String(payload.scene_edge ?? ""),
          state: (["at_scene", "to_hospital", "done"].includes(String(payload.state))
            ? payload.state
            : "at_scene") as HospitalMission["state"],
          recommendedId: String(payload.recommended_id ?? ""),
          chosenId: String(payload.chosen_id ?? ""),
          options: options.map((o) => ({
            facilityId: String(o.facility_id ?? ""),
            name: String(o.name ?? "Hospital"),
            edgeId: String(o.edge_id ?? ""),
            etaS: Number(o.eta_s) || 0,
            at: toLngLat(o.lat, o.lon),
          })),
        },
      },
    });
  },

  applyOffer: (payload) => {
    const incidentId = String(payload.incident_id ?? "");
    if (incidentId) {
      set({
        calls: {
          ...get().calls,
          [incidentId]: {
            incidentId,
            kind: String(payload.kind ?? ""),
            state: String(payload.state ?? "offered") as CallStatus["state"],
            unitId: String(payload.unit_id ?? ""),
            etaS: Number(payload.eta_s) || 0,
            asked: Array.isArray(payload.asked) ? payload.asked.map(String) : [],
            atMs: Date.now(),
          },
        },
      });
    }
    const unitId = typeof payload.unit_id === "string" ? payload.unit_id : "";
    if (!unitId) return;                      // an "exhausted" event names no unit
    const state = String(payload.state ?? "");
    if (state !== "offered") {
      get().clearOffer(unitId);
      return;
    }
    const etaS = Number(payload.eta_s);
    set({
      offers: {
        ...get().offers,
        [unitId]: {
          offerId: String(payload.offer_id ?? ""),
          incidentId: String(payload.incident_id ?? ""),
          unitId,
          kind: String(payload.kind ?? ""),
          edgeId: String(payload.edge_id ?? ""),
          etaS: Number.isFinite(etaS) ? etaS : 0,
          expiresAtMs: Date.now() + OFFER_SECONDS * 1000,
        },
      },
    });
  },

  clearOffer: (unitId) => {
    const { [unitId]: gone, ...rest } = get().offers;
    if (gone) set({ offers: rest });
  },
}));
