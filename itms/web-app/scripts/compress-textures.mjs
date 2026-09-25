/**
 * Compress public/globe/*.jpg → WebP with sharp.
 * Run once: node scripts/compress-textures.mjs
 * The WebP files are committed and referenced by cinematicEarth.ts.
 */
import sharp from "sharp";
import { readdirSync, statSync } from "fs";
import { join, basename, extname } from "path";

const globeDir = new URL("../public/globe", import.meta.url).pathname;

for (const file of readdirSync(globeDir)) {
  const ext = extname(file).toLowerCase();
  if (![".jpg", ".jpeg", ".png"].includes(ext)) continue;
  const input = join(globeDir, file);
  const outName = basename(file, ext) + ".webp";
  const output = join(globeDir, outName);
  const before = statSync(input).size;
  const info = await sharp(input)
    .webp({ quality: 82, effort: 6 })
    .toFile(output);
  const pct = (((before - info.size) / before) * 100).toFixed(0);
  console.log(`${file} → ${outName}: ${(before / 1024).toFixed(0)} KiB → ${(info.size / 1024).toFixed(0)} KiB  (−${pct}%)`);
}
