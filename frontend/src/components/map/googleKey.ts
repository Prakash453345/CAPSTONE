/**
 * Whether a Google Map Tiles key is configured. Kept apart from googleTiles.ts
 * so the basemap can check it without pulling the dormant Google code into
 * every map page's first download (scripts/check-bundle-budget.mjs).
 */
export const GOOGLE_MAPS_KEY: string | undefined = import.meta.env.VITE_GOOGLE_MAPS_API_KEY;

export const hasGoogleKey = Boolean(GOOGLE_MAPS_KEY && GOOGLE_MAPS_KEY !== "your_api_key_here");
