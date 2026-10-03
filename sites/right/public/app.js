// Shared between myleftnut.org and myrightnut.org. The two copies are
// byte-identical (tests/test_sites.py enforces it). Everything that differs
// between the sides is read from <html data-side data-other>.
//
// There is no server, no analytics and no cookies. The only network request
// this page makes is to its sibling's /status.json, and the only thing it
// stores is a few counters in your own browser's localStorage.

(() => {
  "use strict";

  const root = document.documentElement;
  const side = root.dataset.side === "right" ? "right" : "left";
  const otherSide = side === "left" ? "right" : "left";

  // When served locally with `make serve`, the sibling is on the other port.
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(location.hostname);
  const other = local
    ? `${location.protocol}//${location.hostname}:${side === "left" ? 8002 : 8001}`
    : root.dataset.other;

  const store = {
    get(key, fallback) {
      try {
        const raw = localStorage.getItem(`nuts.${key}`);
        return raw === null ? fallback : JSON.parse(raw);
      } catch {
        return fallback;
      }
    },
    set(key, value) {
      try {
        localStorage.setItem(`nuts.${key}`, JSON.stringify(value));
      } catch {
        // Private mode, blocked storage, whatever. The page still works.
      }
    },
  };

  // ---- the orb -----------------------------------------------------------

  const orb = document.getElementById("orb");
  const boops = document.getElementById("boops");
  const boopLines = [
    "", // 0 boops: say nothing
    "Booped once. Reasonable.",
    "Booped twice. Still reasonable.",
    "Booped three times. Okay.",
    "Booped {n} times. We get it.",
    "Booped {n} times. Please stop.",
    "Booped {n} times. This is a lot.",
    "Booped {n} times. The other one is watching.",
    "Booped {n} times. Have you considered the other one?",
    "Booped {n} times. Seriously, go boop the other one.",
    "Booped {n} times. Nothing happens past this point. Nothing.",
  ];

  function renderBoops(n) {
    if (!boops) return;
    const idx = Math.min(n, boopLines.length - 1);
    boops.textContent = boopLines[idx].replace("{n}", String(n));
  }

  if (orb) {
    let count = store.get(`boops.${side}`, 0);
    renderBoops(count);
    const boop = () => {
      count += 1;
      store.set(`boops.${side}`, count);
      renderBoops(count);
      orb.classList.remove("jiggle");
      // Force a reflow so the animation restarts on every click.
      void orb.offsetWidth;
      orb.classList.add("jiggle");
    };
    orb.addEventListener("click", boop);
    orb.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        boop();
      }
    });
  }

  // ---- sibling status ----------------------------------------------------

  const dot = document.getElementById("sibling-dot");
  const siblingText = document.getElementById("sibling-text");

  async function checkSibling() {
    if (!dot || !siblingText) return;
    dot.dataset.state = "pending";
    siblingText.textContent = "checking…";
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 6000);
      const res = await fetch(`${other}/status.json`, {
        cache: "no-store",
        signal: controller.signal,
      });
      clearTimeout(timer);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const mood = typeof data.mood === "string" ? data.mood : "unknown";
      dot.dataset.state = "online";
      siblingText.textContent = `online · ${mood}`;
    } catch {
      dot.dataset.state = "offline";
      siblingText.textContent = "unreachable. Probably fine. Probably.";
    }
  }
  checkSibling();

  // ---- ask the nuts ------------------------------------------------------

  const flipBtn = document.getElementById("flip");
  const question = document.getElementById("question");
  const verdict = document.getElementById("verdict");
  const tally = document.getElementById("tally");

  function renderTally() {
    if (!tally) return;
    const t = store.get("flips", { left: 0, right: 0 });
    const total = t.left + t.right;
    if (total === 0) {
      tally.textContent = "No flips yet on this device.";
      return;
    }
    const mine = t[side];
    tally.textContent =
      `On this device: ${side} ${mine}, ${otherSide} ${total - mine} ` +
      `(${total} flip${total === 1 ? "" : "s"}). Nothing leaves your browser.`;
  }

  function flip() {
    if (!verdict) return;
    const bytes = new Uint8Array(1);
    crypto.getRandomValues(bytes);
    const winner = bytes[0] % 2 === 0 ? "left" : "right";
    const t = store.get("flips", { left: 0, right: 0 });
    t[winner] += 1;
    store.set("flips", t);

    const q = question && question.value.trim();
    const about = q ? ` on “${q.slice(0, 120)}”` : "";
    verdict.dataset.winner = winner;
    verdict.replaceChildren();
    const strong = document.createElement("strong");
    strong.textContent = winner.toUpperCase();
    verdict.append(strong, document.createElement("br"));
    if (winner === side) {
      verdict.append(`The ${side} one has ruled${about}. You are already in the right place.`);
    } else {
      verdict.append(`The ${winner} one has been assigned${about}. Take it up with them: `);
      const a = document.createElement("a");
      a.href = `${root.dataset.other}/`;
      a.textContent = `my${winner}nut.org`;
      verdict.append(a);
    }
    renderTally();
  }

  if (flipBtn) flipBtn.addEventListener("click", flip);
  if (question) {
    question.addEventListener("keydown", (e) => {
      if (e.key === "Enter") flip();
    });
  }
  renderTally();

  // ---- allegiance --------------------------------------------------------

  const pledge = document.getElementById("pledge");
  const pledgeText = document.getElementById("pledge-text");
  const pledgeLines = {
    left: "Noted. You side with the one that hangs lower. A person of the people.",
    right: "Noted. You side with the one that sits higher. A person of standards.",
  };

  function renderPledge() {
    if (!pledge || !pledgeText) return;
    const chosen = store.get("allegiance", null);
    if (chosen === null) {
      pledgeText.textContent =
        "Unofficial tally: nobody yet. We don't have a server, and we don't want your data.";
      pledge.textContent = `Pledge allegiance to the ${side} one`;
    } else {
      pledgeText.textContent = pledgeLines[chosen] || pledgeLines[side];
      pledge.textContent = chosen === side ? "Pledge again (it counts the same)" : `Defect to the ${side} one`;
    }
  }
  if (pledge) {
    pledge.addEventListener("click", () => {
      store.set("allegiance", side);
      renderPledge();
    });
  }
  renderPledge();
})();
