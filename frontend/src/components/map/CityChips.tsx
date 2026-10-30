import { useEffect, useState } from "react";
import { useMapInstance } from "@/components/map/MapContext";
import { MAP_CHIP, MAP_CHIP_ACTIVE } from "@/components/map/mapChrome";
import { SHOWN_CITIES, type CityId } from "@/data/city";
import { cityAt, cityBounds } from "@/data/network";
import { cn } from "@/utils/cn";

/**
 * One chip per city, Google Maps' place chips in the search row: the city in
 * view is highlighted and a tap flies to the other one. Hidden when the
 * console shows a single city.
 */
export function CityChips() {
  const map = useMapInstance();
  const [current, setCurrent] = useState<CityId | null>(() => {
    const c = map.getCenter();
    return cityAt(c.lng, c.lat);
  });

  useEffect(() => {
    const sync = () => {
      const c = map.getCenter();
      setCurrent(cityAt(c.lng, c.lat));
    };
    map.on("moveend", sync);
    return () => {
      map.off("moveend", sync);
    };
  }, [map]);

  const cities = SHOWN_CITIES.filter((c) => cityBounds.has(c.id));
  if (cities.length < 2) return null;

  return (
    <>
      {cities.map((city) => {
        const on = city.id === current;
        return (
          <button
            key={city.id}
            type="button"
            aria-pressed={on}
            onClick={() => {
              const b = cityBounds.get(city.id)!;
              map.fitBounds(
                [
                  [b.minLng, b.minLat],
                  [b.maxLng, b.maxLat],
                ],
                { padding: 64, duration: 1100 },
              );
            }}
            className={cn(MAP_CHIP, on && MAP_CHIP_ACTIVE)}
          >
            {city.name}
          </button>
        );
      })}
    </>
  );
}
