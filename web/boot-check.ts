// Checks boot.js in a real Chromium against a built dist that has a #fallback
// block, like the demo of hilen:
// 1. a slow wasm, the block stays hidden while the page loads and after it
//    started,
// 2. a wasm that fails to load, the block shows,
// 3. a lost WebGL context, the engine drops the canvas and the block shows.
// The 3rd needs a dist built with the webgl feature.
//
//   bun build/web/boot-check.ts <dist> [--chromium /path/to/chromium]

import { parseArgs } from "node:util";
import { existsSync, readFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { chromium, type Page } from "playwright-core";

const { values: args, positionals } = parseArgs({
    allowPositionals: true,
    options: { chromium: { type: "string", default: "chromium" } },
});

const dist = positionals[0];
if (!dist || !existsSync(join(dist, "index.html"))) {
    console.error("usage: bun build/web/boot-check.ts <dist with index.html>");
    process.exit(2);
}

const types: Record<string, string> = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".wasm": "application/wasm",
    ".json": "application/json",
    ".css": "text/css",
};

// The wasm answer of the next page load: late, missing or normal.
let wasmMode: "slow" | "missing" | "normal" = "normal";

const server = Bun.serve({
    port: 0,
    async fetch(request) {
        const path = new URL(request.url).pathname;
        const file = normalize(join(dist, path === "/" ? "index.html" : path));
        if (!file.startsWith(normalize(dist)) || !existsSync(file)) {
            return new Response("not found", { status: 404 });
        }
        if (file.endsWith(".wasm")) {
            if (wasmMode === "missing") {
                return new Response("not found", { status: 404 });
            }
            if (wasmMode === "slow") {
                await Bun.sleep(4000);
            }
        }
        return new Response(readFileSync(file), {
            headers: { "content-type": types[extname(file)] ?? "application/octet-stream" },
        });
    },
});
const base = `http://localhost:${server.port}/`;

const browser = await chromium.launch({
    executablePath: args.chromium,
    args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});

function fallbackShown(page: Page): Promise<boolean> {
    return page.evaluate(() => {
        const block = document.getElementById("fallback");
        return block !== null && getComputedStyle(block).display !== "none";
    });
}

function hasCanvas(page: Page): Promise<boolean> {
    return page.evaluate(() => document.querySelector("body > canvas") !== null);
}

let failures = 0;
function check(name: string, ok: boolean) {
    console.log(`${ok ? "pass" : "FAIL"}  ${name}`);
    if (!ok) {
        failures += 1;
    }
}

async function fresh(): Promise<Page> {
    const page = await (await browser.newContext()).newPage();
    page.on("console", (message) => {
        if (message.type() === "error") {
            console.log(`  page error: ${message.text().slice(0, 200)}`);
        }
    });
    return page;
}

{
    wasmMode = "slow";
    const page = await fresh();
    await page.goto(base, { waitUntil: "domcontentloaded" });
    await Bun.sleep(1500);
    check("slow wasm, the block is hidden while the page loads", !(await fallbackShown(page)));
    check("slow wasm, no canvas yet", !(await hasCanvas(page)));
    await page.waitForSelector("body > canvas", { state: "attached", timeout: 60_000 });
    check("slow wasm, the block is hidden after the start", !(await fallbackShown(page)));
    await page.context().close();
}

{
    wasmMode = "missing";
    const page = await fresh();
    await page.goto(base, { waitUntil: "load" });
    await Bun.sleep(1500);
    check("missing wasm, the block shows", await fallbackShown(page));
    await page.context().close();
}

{
    wasmMode = "normal";
    const page = await fresh();
    await page.goto(`${base}?hilen_webgl`, { waitUntil: "load" });
    await page.waitForSelector("body > canvas", { state: "attached", timeout: 60_000 });
    await Bun.sleep(2000);
    const lost = await page.evaluate(() => {
        const canvas = document.querySelector("body > canvas") as HTMLCanvasElement;
        const gl = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
        const extension = gl?.getExtension("WEBGL_lose_context");
        extension?.loseContext();
        return extension !== null && extension !== undefined;
    });
    check("lost context, the page has WEBGL_lose_context", lost);
    await Bun.sleep(1500);
    check("lost context, the canvas is gone", !(await hasCanvas(page)));
    check("lost context, the block shows", await fallbackShown(page));
    await page.context().close();
}

await browser.close();
server.stop();
console.log(failures === 0 ? "all passed" : `${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
