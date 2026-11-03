// Hides the #fallback block of a hilen page while the app loads, so a reload
// shows no raw landing or search text before the canvas. The block stays in
// the html for a crawler, and a browser with no JavaScript shows it. A page
// that fails to load or to draw shows it again. trunk pastes this file as a
// plain script with `<link data-trunk rel="inline" href=".../build/web/boot.js" />`
// in the head, so it runs before the first paint. Old browsers like Chromium
// 79 of a TV run it too, so it keeps to old JavaScript. See docs/wasm.md of hilen.
(function () {
    var root = document.documentElement;
    root.classList.add("hilen-loading");

    // 2 rules, so a browser with no :has still keeps the first.
    var style = document.createElement("style");
    style.textContent =
        ".hilen-loading #fallback { display: none; }\n" + "body:has(canvas) #fallback { display: none; }";
    document.head.appendChild(style);

    // A failed script or wasm fetch, a missing WebAssembly and a panic at start
    // all end here. Once the canvas is up, an error is the app's own and the
    // block stays hidden. A GPU failure raises nothing, the engine takes the
    // class off in drop_canvas.
    function failed(event) {
        if (document.querySelector("body > canvas")) {
            return;
        }
        var target = event.target;
        if (target && target !== window && target.tagName !== "SCRIPT") {
            return;
        }
        root.classList.remove("hilen-loading");
    }
    window.addEventListener("error", failed, true);
    window.addEventListener("unhandledrejection", failed);
})();
