import { chromium } from "@playwright/test";
import fs from "node:fs";
const [file, ...rest] = process.argv.slice(2);
const pts = JSON.parse(rest.join(" "));
const b = await chromium.launch({ channel: "chrome" });
const p = await b.newPage();
const data = "data:image/" + (file.endsWith("png") ? "png" : "webp") + ";base64," + fs.readFileSync(file).toString("base64");
const out = await p.evaluate(async ({ data, pts }) => {
  const img = new Image(); img.src = data; await img.decode();
  const c = document.createElement("canvas"); c.width = img.width; c.height = img.height;
  const g = c.getContext("2d"); g.drawImage(img, 0, 0);
  const r = { size: [img.width, img.height] };
  for (const [k, [x, y]] of Object.entries(pts)) {
    // median of a 5x5 patch
    const d = g.getImageData(x - 2, y - 2, 5, 5).data; const ch = [[], [], []];
    for (let i = 0; i < d.length; i += 4) for (let j = 0; j < 3; j++) ch[j].push(d[i + j]);
    r[k] = "#" + ch.map((a) => a.sort((m, n) => m - n)[12].toString(16).padStart(2, "0")).join("");
  }
  return r;
}, { data, pts });
console.log(out); await b.close();
