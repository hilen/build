// Browser UI test lane driver. Builds the atomics wasm, serves dist with the
// isolation headers, and reads the suite report over the inspect WebSocket
// instead of scraping the console, so it drives any real installed browser
// with no automation protocol. See docs/ui-tests.md and docs/inspect.md.
//
//   bun build/web/drive.ts [--browser firefox|chrome|none] [--only "Name,Name"]
//                          [--port 44810] [--timeout 900] [--stall 180] [--no-build]
//                          [--human] [--present --only "Name"] [--webgl]
//
// --webgl draws on WebGL also where the browser has WebGPU, like a TV.

import { parseArgs } from "node:util";
import { existsSync, mkdirSync, mkdtempSync, openSync, readFileSync, rmSync, writeFileSync, writeSync } from "node:fs";
import { join, normalize } from "node:path";
import { tmpdir } from "node:os";

const { values: args } = parseArgs({
    options: {
        browser: { type: "string", default: "chrome" },
        only: { type: "string" },
        port: { type: "string", default: "44810" },
        timeout: { type: "string", default: "900" },
        stall: { type: "string", default: "180" },
        "no-build": { type: "boolean", default: false },
        human: { type: "boolean", default: false },
        present: { type: "boolean", default: false },
        webgl: { type: "boolean", default: false },
    },
});

// Presentation mode shows one view full screen for a human to play with.
// No suite runs and no report ever comes, so it needs the one name and it
// never times out.
if (args.present && (!args.only || args.only.includes(","))) {
    console.error("--present requires exactly one --only name");
    process.exit(1);
}

const root = normalize(join(import.meta.dir, "..", ".."));
const appDir = join(root, "demo");
const dist = join(appDir, "dist");
const port = Number(args.port);

// rustc adds none of the threading flags itself, see docs/roadmap.md.
const RUSTFLAGS = [
    "-C target-feature=+atomics,+bulk-memory,+mutable-globals",
    "-C link-arg=--shared-memory",
    "-C link-arg=--import-memory",
    "-C link-arg=--max-memory=2147483648",
    "-C link-arg=--export=__wasm_init_tls",
    "-C link-arg=--export=__tls_size",
    "-C link-arg=--export=__tls_align",
    "-C link-arg=--export=__tls_base",
    "-C link-arg=--export=__heap_base",
    "-C link-arg=--export=__data_end",
].join(" ");

if (!args["no-build"]) {
    console.log("building atomics wasm with trunk");
    const build = Bun.spawnSync(["trunk", "build", ...(args.webgl ? ["--features", "webgl"] : [])], {
        cwd: appDir,
        env: {
            ...process.env,
            RUSTFLAGS,
            CARGO_UNSTABLE_BUILD_STD: "std,panic_abort",
        },
        stdout: "inherit",
        stderr: "inherit",
    });
    if (build.exitCode !== 0) {
        console.error("trunk build failed");
        process.exit(1);
    }
}

let browserProc: ReturnType<typeof Bun.spawn> | undefined;
const profileDirs: string[] = [];
let appSocket: Bun.ServerWebSocket<unknown> | undefined;
let finished = false;
let pendingExit: number | undefined;

// A wasm panic aborts the whole instance, there is no unwinding to catch it,
// so one panicking test would hide every test after it. The panic beacon
// names the test, the driver records it failed, relaunches the browser with
// the dead tests in `hilen_test_skip`, and merges them into the final report.
const panicked: { name: string; detail: string }[] = [];

// A relaunch storm means something below the tests is broken, stop it.
const MAX_RELAUNCHES = 25;

// A browser that dies or never opens its window says why on stderr, and
// throwing that away leaves nothing to read but a silent timeout.
const outDir = join(root, "target", "web-test");
mkdirSync(outDir, { recursive: true });
const browserLogPath = join(outDir, `browser-${args.browser}.log`);
const browserLog = args.browser === "none" ? undefined : openSync(browserLogPath, "w");

// The app's own log lines arrive over the inspect socket as the app writes
// them, printed live like the desktop lane prints its stdout and kept in a
// file next to the browser's. A stuck run then names the test it stopped
// on and the last thing the app said, see the stall watchdog below.
const appLogPath = join(outDir, `app-${args.browser}.log`);
const appLog = openSync(appLogPath, "w");
let lastActivity = Date.now();
let lastLine = "";

function appLine(level: string, message: string) {
    const line = level === "INFO" ? message : `[${level}] ${message}`;
    console.log(line);
    writeSync(appLog, `${line}\n`);
    lastActivity = Date.now();
    lastLine = line;
}

function printBrowserLog() {
    if (!browserLog) return;
    let text = "";
    try {
        text = readFileSync(browserLogPath, "utf8").trim();
    } catch {
        return;
    }
    if (!text) return;
    console.error(`last browser output:\n${text.split("\n").slice(-40).join("\n")}`);
}

function finish(code: number) {
    if (finished) return;
    finished = true;
    if (code !== 0) printBrowserLog();
    browserProc?.kill();
    for (const dir of profileDirs) rmSync(dir, { recursive: true, force: true });
    // Give the kill a moment so the browser does not outlive the server.
    setTimeout(() => process.exit(code), 500);
}

// Asks the app for a screenshot over the inspect socket before exiting, CI
// uploads it as the failure artifact. Falls through when the app is gone.
function failWithScreenshot(code: number) {
    if (finished) return;
    if (!appSocket || appSocket.readyState !== 1) return finish(code);
    pendingExit = code;
    appSocket.send('"Screenshot"');
    setTimeout(() => finish(code), 10_000);
}

process.on("SIGINT", () => finish(130));

// A browser aborts asset requests it no longer needs. The aborted stream
// surfaces as an async error that must not kill the driver mid run.
process.on("unhandledRejection", (err) => {
    console.log(`ignored async error: ${err}`);
});

const server = Bun.serve({
    port,
    // The default of 10 seconds cut a multi megabyte CJK font mid body on
    // a slow runner, the app then ran the suite with the default font and
    // failed on pixels. 255 is the most Bun allows.
    idleTimeout: 255,
    fetch(req, server) {
        const url = new URL(req.url);

        if (url.pathname === "/hilen-inspect") {
            return server.upgrade(req) ? undefined : new Response("upgrade failed", { status: 400 });
        }

        // The body must be read before the response returns. Answering first
        // tears the request down, `text()` then rejects with an AbortError,
        // and the panic is swallowed by the unhandled rejection handler.
        if (url.pathname === "/te-panic" && req.method === "POST") {
            const testName = req.headers.get("x-te-test");
            return req.text().then((body) => {
                if (testName && panicked.length < MAX_RELAUNCHES) {
                    console.error(`TEST PANICKED: ${testName}`);
                    panicked.push({ name: testName, detail: body });
                    relaunchBrowser();
                } else {
                    // No test name means the app died outside a test, a
                    // relaunch would just die the same way.
                    console.error(`APP PANIC: ${body}`);
                    finish(1);
                }
                return new Response(null, { status: 204 });
            });
        }

        let path = normalize(url.pathname);
        if (path.includes("..")) return new Response("forbidden", { status: 403 });
        if (path === "/") path = "/index.html";

        const file = Bun.file(join(dist, path));
        return file.exists().then((exists) => {
            if (!exists) return new Response("not found", { status: 404 });
            return new Response(file, {
                headers: {
                    // Workers with shared wasm memory need cross origin isolation.
                    "Cross-Origin-Opener-Policy": "same-origin",
                    "Cross-Origin-Embedder-Policy": "require-corp",
                    "Cache-Control": "no-store",
                },
            });
        });
    },
    error(err) {
        console.log(`server error: ${err}`);
        return new Response(null, { status: 500 });
    },
    websocket: {
        open(ws) {
            appSocket = ws;
            lastActivity = Date.now();
            console.log("app connected to the inspect socket");
        },
        message(_ws, message) {
            const frame = JSON.parse(String(message));
            lastActivity = Date.now();

            if (frame.Log) {
                appLine(frame.Log.level, frame.Log.message);
                return;
            }

            if (frame.TestResults) {
                const { total, failures } = frame.TestResults;
                for (const p of panicked) {
                    failures.push({ name: p.name, detail: p.detail });
                }
                for (const failure of failures) {
                    console.error(`TEST FAILED: ${failure.name}\n${failure.detail}`);
                }
                console.log(`HILEN_TEST_RESULT ${total + panicked.length} tests, ${failures.length} failed`);
                if (failures.length > 0) failWithScreenshot(1);
                else finish(0);
                return;
            }

            // A test pushes its frame the moment it fails, the page has
            // nowhere to keep it. One file per test, CI uploads the dir.
            if (frame.FailureScreenshot) {
                const { test, png_base64 } = frame.FailureScreenshot;
                const dir = join(root, "target", "web-test", "failures");
                mkdirSync(dir, { recursive: true });
                const shot = join(dir, `${test.replace(/[^A-Za-z0-9_-]+/g, "_")}.png`);
                writeFileSync(shot, Buffer.from(png_base64, "base64"));
                console.log(`failure screenshot for ${test} saved to ${shot}`);
                return;
            }

            if (frame.Screenshot) {
                const shotDir = join(root, "target", "web-test");
                mkdirSync(shotDir, { recursive: true });
                const shot = join(shotDir, "ui-web-failure.png");
                writeFileSync(shot, Buffer.from(frame.Screenshot.png_base64, "base64"));
                console.log(`failure screenshot saved to ${shot}`);
                finish(pendingExit ?? 1);
                return;
            }

            console.log(`unexpected inspect frame: ${String(message)}`);
        },
        close(ws) {
            // A relaunched page connects before the dead page's socket
            // times out, so only the owner may clear the slot.
            if (appSocket !== ws) return;
            appSocket = undefined;
            if (!finished) console.log("inspect socket closed");
        },
    },
});

function testUrl(): string {
    let query = args.present ? "?hilen_present=1&hilen_inspect=1" : "?hilen_run_tests=1&hilen_inspect=1";
    if (args.human) {
        query += "&hilen_human=1";
    }
    if (args.webgl) {
        query += "&hilen_webgl=1";
    }
    // Encode names one by one. Encoding the whole list turns the commas
    // into %2C, and the app splits the raw query on plain commas.
    if (args.only) {
        query += `&hilen_test_only=${args.only
            .split(",")
            .map((name) => encodeURIComponent(name.trim()))
            .join(",")}`;
    }
    if (panicked.length > 0) {
        query += `&hilen_test_skip=${panicked.map((p) => encodeURIComponent(p.name)).join(",")}`;
    }
    return `http://localhost:${server.port}/${query}`;
}

console.log(`serving ${dist} at ${testUrl()}`);

// A missing browser must fail the lane at once, a spawn error would
// otherwise surface as a silent hang until the timeout.
function browserBinary(name: string, candidates: (string | null)[]): string {
    const found = candidates.find((c) => c && existsSync(c));
    if (!found) {
        console.error(`${name} is not installed`);
        process.exit(1);
    }
    return found;
}

// Always a real installed browser, headed, with a throwaway profile.
// Headless reports different GPU state and Playwright ships patched builds,
// neither says anything about what users run.

// Color probes read the real surface, so the viewport must fit the biggest
// test canvas, 640 by 1136 physical pixels. The linux runner renders at
// scale 1 and browser chrome eats up to 150 pixels, so the window needs
// this much height. A physical screen clamps it, which is fine on a mac
// where scale 2 doubles the pixels anyway.
const WINDOW_HEIGHT = 1300;

function launchFirefox(url: string) {
    const profileDir = mkdtempSync(join(tmpdir(), "te-firefox-"));
    profileDirs.push(profileDir);
    writeFileSync(
        join(profileDir, "user.js"),
        [
            'user_pref("dom.webgpu.enabled", true);',
            // A covered window throttles the refresh driver to 1 fps, which
            // stalls the suite the way Chrome occlusion does. Keep full rate.
            'user_pref("layout.throttled_frame_rate", 60);',
            'user_pref("browser.shell.checkDefaultBrowser", false);',
            'user_pref("browser.aboutwelcome.enabled", false);',
            // Firefox 136 and newer opens a Terms of Use modal on a fresh
            // profile. It covers the page, the browser stops rendering behind
            // it, and the suite freezes until the driver gives up. The
            // aboutwelcome pref above does not suppress this one.
            'user_pref("termsofuse.bypassNotification", true);',
            'user_pref("datareporting.policy.dataSubmissionPolicyBypassNotification", true);',
            'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
            'user_pref("app.update.disabledForTesting", true);',
            // Every test logs "Started" and "OK" through the console, so this
            // puts the suite's own progress in the browser log. Without it a
            // stuck run says nothing about which test it stopped on.
            'user_pref("devtools.console.stdout.content", true);',
        ].join("\n"),
    );
    browserProc = Bun.spawn(
        [
            browserBinary("firefox", ["/Applications/Firefox.app/Contents/MacOS/firefox", Bun.which("firefox")]),
            "-no-remote",
            "-new-instance",
            "-profile",
            profileDir,
            "-width",
            "760",
            "-height",
            String(WINDOW_HEIGHT),
            url,
        ],
        { stdout: browserLog, stderr: browserLog },
    );
}

function launchChrome(url: string) {
    const profileDir = mkdtempSync(join(tmpdir(), "te-chrome-"));
    profileDirs.push(profileDir);
    browserProc = Bun.spawn(
        [
            browserBinary("chrome", [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                Bun.which("google-chrome"),
                Bun.which("chromium"),
            ]),
            `--user-data-dir=${profileDir}`,
            "--no-first-run",
            "--no-default-browser-check",
            // Chrome suspends rendering when another window fully covers this
            // one. Frames stop, animations freeze and the suite stalls until
            // uncovered. Reproduced by covering the window during a present.
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            // A machine with no GPU, which is every CI linux runner, offers no
            // WebGPU adapter at all without these two. `requestAdapter` then
            // resolves to null, the engine cannot start, and the page goes
            // quiet with nothing to read. The second one lets Dawn fall back to
            // the SwiftShader vulkan driver Chrome ships with itself.
            "--enable-unsafe-webgpu",
            "--enable-unsafe-swiftshader",
            // On linux the GPU process boots Vulkan for WebGPU. Left alone it
            // probes the real driver and a vulkan surface against the X
            // server, both absent on a GPU-less runner, and dies during init.
            // After a few crashes Chrome settles into software compositing,
            // where a WebGPU swap chain cannot exist, so the device is lost
            // and the app panics on its first buffer. These route vulkan
            // through the SwiftShader build Chrome ships and keep the
            // compositor off vulkan surfaces. Linux only, a mac has Metal.
            ...(process.platform === "linux"
                ? [
                      "--enable-features=Vulkan",
                      "--use-angle=vulkan",
                      "--use-vulkan=swiftshader",
                      "--use-webgpu-adapter=swiftshader",
                      "--disable-vulkan-surface",
                  ]
                : []),
            `--window-size=760,${WINDOW_HEIGHT}`,
            "--new-window",
            url,
        ],
        { stdout: browserLog, stderr: browserLog },
    );
}

function launchBrowser() {
    if (args.browser === "firefox") {
        launchFirefox(testUrl());
    } else if (args.browser === "chrome") {
        launchChrome(testUrl());
    } else if (args.browser !== "none") {
        console.error(`unknown browser: ${args.browser}`);
        finish(1);
    }
}

function relaunchBrowser() {
    browserProc?.kill();
    launchBrowser();
}

launchBrowser();

// A human run holds after every test until ctrl, so any timeout would
// just kill the review it exists to enable.
if (args.present) {
    console.log("presentation mode, close the browser or ctrl-c to finish");
} else if (args.human) {
    console.log("human mode, ctrl in the browser advances each test");
} else {
    setTimeout(() => {
        console.error(`no report after ${args.timeout} seconds`);
        failWithScreenshot(1);
    }, Number(args.timeout) * 1000);

    // A test that never finishes used to look like nothing until the
    // timeout above. The app logs every test it starts, so a long silence
    // is a stuck test, and the last line names it.
    const stall = Number(args.stall);
    setInterval(() => {
        const idle = (Date.now() - lastActivity) / 1000;
        if (idle < stall || finished) return;
        console.error(`no output from the app for ${Math.round(idle)} seconds, last line: ${lastLine || "none"}`);
        failWithScreenshot(1);
    }, 5_000);
}
