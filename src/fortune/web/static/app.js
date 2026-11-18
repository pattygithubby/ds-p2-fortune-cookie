/* Fortune Cookie: app.js. Plain JavaScript, no libraries. */
(function () {
  "use strict";

  /* ==================================================================
     DEMO MODE (open the page with ?demo)
     A small fake API so the page can be previewed and recorded without
     a server. Fortunes come from the list below with 10–40 ms latency.
     Every 5th request starts a simulated failover: about 4 s of network
     errors and 503 "not the leader" replies, after which the leader
     changes 3 → 2 → 3 … (pods bully-2 / bully-1).
     ================================================================== */
  var DEMO = new URLSearchParams(location.search).has("demo");

  var demoApi = (function () {
    var FORTUNES = [
      "When in doubt, hold an election.",
      "A quiet node hears the heartbeat first.",
      "Good things come to those who retry with exponential backoff.",
      "The highest number does not always win, but today it does.",
      "Every partition heals in time. Be patient with yours.",
      "An old friend will reach out to you after a brief timeout.",
      "Small kindnesses, like caches, are eventually consistent.",
      "A leader who stops sending heartbeats is soon politely replaced.",
      "You will find consensus where you least expect it.",
      "A long journey begins with a single idempotent step.",
      "Even the smallest pod can lead when the others fall silent.",
      "Trust the process, but check its process ID.",
      "Fortune favours the patient client who keeps retrying quietly while the cluster sorts itself out.",
      "Today is a good day to replicate your happiness across every zone.",
      "The bug you seek lives in the last thing you deployed."
    ];
    var PODS = { 3: "bully-2", 2: "bully-1" };
    var leader = 3;
    var requests = 0;
    var downUntil = 0;
    var next = Math.floor(Math.random() * FORTUNES.length);

    return function () {
      return new Promise(function (resolve, reject) {
        var now = Date.now();
        // Count requests made while the cluster is healthy; every 5th one kills the leader.
        if (now >= downUntil && ++requests % 5 === 0) {
          downUntil = now + 4000;
          leader = leader === 3 ? 2 : 3;
        }
        setTimeout(function () {
          if (Date.now() < downUntil) {
            if (Math.random() < 0.5) {
              reject(new TypeError("Failed to fetch (demo failover)"));
            } else {
              resolve({ status: 503, body: { error: "not the leader", leader: null, pod: PODS[leader] } });
            }
            return;
          }
          resolve({
            status: 200,
            body: { fortune: FORTUNES[next++ % FORTUNES.length], leader: leader, pod: PODS[leader] }
          });
        }, 10 + Math.random() * 30);
      });
    };
  })();

  /* ==================================================================
     Server API and retry policy
     ================================================================== */
  var REQUEST_TIMEOUT_MS = 3000;
  var BACKOFF_START_MS = 250;
  var BACKOFF_MAX_MS = 1000;
  var GIVE_UP_MS = 15000;

  function timeoutSignal(ms) {
    if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
      return AbortSignal.timeout(ms);
    }
    var controller = new AbortController();
    setTimeout(function () { controller.abort(); }, ms);
    return controller.signal;
  }

  function serverApi(timeoutMs) {
    return fetch("/api/fortune", {
      cache: "no-store",
      headers: { Accept: "application/json" },
      signal: timeoutSignal(timeoutMs)
    }).then(function (res) {
      return res.json().then(
        function (body) { return { status: res.status, body: body }; },
        function () { return { status: res.status, body: null }; }
      );
    });
  }

  var api = DEMO ? demoApi : serverApi;

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  // One fortune, retrying quietly through a failover. Resolves with
  // { fortune, leader, pod, ms } or rejects after GIVE_UP_MS in total.
  async function fetchFortune(startedAt, onRetry) {
    var delay = BACKOFF_START_MS;
    for (var retry = 1; ; retry++) {
      var remaining = GIVE_UP_MS - (performance.now() - startedAt);
      if (remaining <= 0) break;
      try {
        var res = await api(Math.min(REQUEST_TIMEOUT_MS, remaining));
        var body = res.body;
        if (res.status === 200 && body && typeof body.fortune === "string" && body.fortune.trim()) {
          return {
            fortune: body.fortune.trim(),
            leader: body.leader,
            pod: body.pod,
            ms: performance.now() - startedAt
          };
        }
        // 503 "not the leader" (or anything unexpected): retry.
      } catch (err) {
        // Network error or timeout while a new leader is elected: retry.
      }
      if (performance.now() - startedAt + delay >= GIVE_UP_MS) break;
      onRetry(retry);
      await sleep(delay);
      delay = Math.min(delay * 2, BACKOFF_MAX_MS);
    }
    throw new Error("unavailable");
  }

  /* ==================================================================
     Page
     ================================================================== */
  var root = document.documentElement;
  var $ = function (id) { return document.getElementById(id); };
  var stage = $("stage");
  var halfL = stage.querySelector(".half-l");
  var fortuneEl = $("fortune");
  var button = $("next");
  var badge = $("badge");
  var badgeText = $("badge-text");
  var badgeNew = $("badge-new");
  var toggle = $("theme-toggle");

  if (DEMO) $("demo-tag").hidden = false;

  // Animation timings come from the CSS custom properties.
  function cssMs(name) {
    var v = getComputedStyle(root).getPropertyValue(name).trim();
    var n = parseFloat(v);
    if (isNaN(n)) return 0;
    return /ms$/.test(v) ? n : n * 1000;
  }

  function formatTime(ms) {
    return ms < 1000 ? Math.max(1, Math.round(ms)) + " ms" : (ms / 1000).toFixed(1) + " s";
  }

  function setBadge(state, text, isNewLeader) {
    badge.setAttribute("data-state", state);
    badgeNew.hidden = !isNewLeader;
    badgeText.textContent = text;
    badge.classList.remove("is-new");
    if (isNewLeader) {
      void badge.offsetWidth; // restart the glow
      badge.classList.add("is-new");
    }
  }

  // Resolves the moment the closing halves meet: when their transform transition ends,
  // at once if there is no transition (reduced motion), or after a timeout as a safety net.
  function halvesMeet() {
    return new Promise(function (resolve) {
      if (parseFloat(getComputedStyle(halfL).transitionDuration) === 0) return resolve();
      var done = false;
      function finish() {
        if (done) return;
        done = true;
        halfL.removeEventListener("transitionend", onEnd);
        resolve();
      }
      function onEnd(e) {
        if (e.target === halfL && e.propertyName === "transform") finish();
      }
      halfL.addEventListener("transitionend", onEnd);
      setTimeout(finish, cssMs("--t-close") + 80);
    });
  }

  // Resolves once a frame has been painted, so even a split-second touch shows the crack.
  // The timeout covers background tabs, where animation frames don't run.
  function nextPaint() {
    return new Promise(function (resolve) {
      requestAnimationFrame(function () { requestAnimationFrame(resolve); });
      setTimeout(resolve, 100);
    });
  }

  function closeCookie() {
    stage.classList.remove("is-note");
    if (!stage.classList.contains("is-open")) return Promise.resolve();
    stage.classList.remove("is-open");
    return halvesMeet().then(function () {
      stage.classList.add("is-shut");
      return nextPaint();
    });
  }

  function openCookie() {
    // Same frame: the crack disappears exactly as the halves start to part
    stage.classList.remove("is-shut");
    stage.classList.add("is-open");
  }

  var busy = false;
  var lastLeader = null;

  async function getAnotherCookie() {
    if (busy) return;
    busy = true;
    var hadFocus = document.activeElement === button;
    button.disabled = true;

    var startedAt = performance.now();
    var settled = false;

    // The cookie closes while the request is already on its way.
    var closed = closeCookie().then(function () {
      if (!settled) stage.classList.add("is-waiting");
    });

    var result = null;
    try {
      result = await fetchFortune(startedAt, function (retry) {
        setBadge("electing", "Electing a new leader… retry " + retry, false);
      });
    } catch (err) {
      result = null;
    }
    settled = true;
    await closed;
    stage.classList.remove("is-waiting");

    if (result) {
      var leader = result.leader == null ? "?" : result.leader;
      var isNewLeader = lastLeader !== null && leader !== lastLeader;
      lastLeader = leader;
      fortuneEl.classList.remove("is-muted");
      fortuneEl.textContent = result.fortune;
      setBadge("ok", "node " + leader + " · " + (result.pod || "unknown pod") + " · " + formatTime(result.ms), isNewLeader);
      openCookie();
    } else {
      fortuneEl.classList.add("is-muted");
      fortuneEl.textContent = "No fortune this time. Give it a moment, then try again.";
      stage.classList.add("is-note");
      setBadge("down", "Can't reach the cookie jar, try again", false);
    }

    busy = false;
    button.disabled = false;
    if (hadFocus) button.focus({ preventScroll: true });
  }

  button.addEventListener("click", getAnotherCookie);

  /* ==================================================================
     Theme: follows the system until the visitor picks one.
     ================================================================== */
  var THEME_KEY = "fortune-theme";
  var media = window.matchMedia ? matchMedia("(prefers-color-scheme: dark)") : null;

  function readTheme() {
    try {
      var v = localStorage.getItem(THEME_KEY);
      return v === "dark" || v === "light" ? v : null;
    } catch (e) {
      return null;
    }
  }

  var chosenTheme = readTheme();

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    toggle.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
  }

  applyTheme(chosenTheme || (media && media.matches ? "dark" : "light"));

  toggle.addEventListener("click", function () {
    chosenTheme = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    applyTheme(chosenTheme);
    try { localStorage.setItem(THEME_KEY, chosenTheme); } catch (e) { /* storage blocked */ }
  });

  if (media) {
    var follow = function (e) { if (!chosenTheme) applyTheme(e.matches ? "dark" : "light"); };
    if (media.addEventListener) media.addEventListener("change", follow);
    else if (media.addListener) media.addListener(follow);
  }

  /* ==================================================================
     Style: classic or Chinese ("festive"), remembered per visitor.
     ================================================================== */
  var STYLE_KEY = "fortune-style";
  var styleToggle = $("style-toggle");

  function applyStyle(style) {
    if (style === "festive") root.setAttribute("data-style", "festive");
    else root.removeAttribute("data-style");
    styleToggle.setAttribute("aria-pressed", style === "festive" ? "true" : "false");
  }

  applyStyle(root.getAttribute("data-style") === "festive" ? "festive" : "classic");

  styleToggle.addEventListener("click", function () {
    var style = root.getAttribute("data-style") === "festive" ? "classic" : "festive";
    applyStyle(style);
    try { localStorage.setItem(STYLE_KEY, style); } catch (e) { /* storage blocked */ }
  });

  // First fortune on page load.
  getAnotherCookie();
})();
