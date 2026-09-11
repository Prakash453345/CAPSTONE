import { beforeEach, describe, expect, it } from "vitest";
import {
  DEFAULT_MAP_LAYERS,
  DEFAULT_CENTER,
  DEFAULT_ZOOM,
  useMapStore,
} from "@/store/mapStore";

function reset() {
  useMapStore.setState({
    activeLayers: new Set(DEFAULT_MAP_LAYERS),
    interactionMode: "idle",
    focus: { center: DEFAULT_CENTER, zoom: DEFAULT_ZOOM, nonce: 0 },
    center: DEFAULT_CENTER,
    zoom: DEFAULT_ZOOM,
  });
}

describe("mapStore", () => {
  beforeEach(reset);

  it("toggleLayer removes then re-adds a layer", () => {
    const { toggleLayer } = useMapStore.getState();
    toggleLayer("anomalies");
    expect(useMapStore.getState().activeLayers.has("anomalies")).toBe(false);
    toggleLayer("anomalies");
    expect(useMapStore.getState().activeLayers.has("anomalies")).toBe(true);
  });

  it("setInteractionMode drives the map-click mode", () => {
    useMapStore.getState().setInteractionMode("pick-source");
    expect(useMapStore.getState().interactionMode).toBe("pick-source");
  });

  it("focusOn moves the centre and bumps the nonce every call", () => {
    const { focusOn } = useMapStore.getState();
    focusOn({ longitude: 80.7, latitude: 16.6 });
    const first = useMapStore.getState().focus;
    expect(first.nonce).toBe(1);
    expect(first.center).toEqual({ longitude: 80.7, latitude: 16.6 });
    focusOn({ longitude: 80.7, latitude: 16.6 }); // same point still re-fires
    expect(useMapStore.getState().focus.nonce).toBe(2);
  });
});
