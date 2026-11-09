import { chromium } from "@playwright/test";
import fs from "node:fs";
const [file, out, x, y, w, h, scale = "2"] = process.argv.slice(2);
const b = await chromium.launch({ channel: "chrome" });
const p = await b.newPage({ viewport: { width: +w * +scale, height: +h * +scale } });
await p.setContent(`<body style="margin:0;overflow:hidden"><div style="width:${+w * +scale}px;height:${+h * +scale}px;background:url(data:image/png;base64,${fs.readFileSync(file).toString("base64")}) -${+x * +scale}px -${+y * +scale}px / auto;image-rendering:pixelated;transform-origin:0 0"></div></body>`);
await p.evaluate((s) => { document.querySelector("div").style.backgroundSize = `${2880 * s}px auto`; }, +scale);
await p.screenshot({ path: out }); await b.close();
