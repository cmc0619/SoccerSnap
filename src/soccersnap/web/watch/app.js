const gate = document.getElementById("gate");
const app = document.getElementById("app");
const loginForm = document.getElementById("loginForm");
const gateMsg = document.getElementById("gateMsg");
const gameList = document.getElementById("gameList");
const gameTitle = document.getElementById("gameTitle");
const player = document.getElementById("player");
const timeline = document.getElementById("timeline");
const chips = document.getElementById("chips");
const searchForm = document.getElementById("searchForm");
const logoutBtn = document.getElementById("logoutBtn");

let session = null;
let currentGame = null;

const QUICK = ["goals", "saves", "shots", "corners", "#9"];

function showApp() {
  gate.hidden = true;
  app.hidden = false;
  logoutBtn.hidden = false;
}

function showGate() {
  gate.hidden = false;
  app.hidden = true;
  logoutBtn.hidden = true;
}

function fmt(ms) {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderTimeline(events) {
  timeline.innerHTML = "";
  for (const e of events) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.ms = String(e.t_start_ms);
    const t = document.createElement("span");
    t.className = "t";
    t.textContent = fmt(e.t_start_ms);
    btn.appendChild(t);
    btn.appendChild(
      document.createTextNode(
        ` ${e.label || e.type}${e.jersey_number ? ` · #${e.jersey_number}` : ""}`
      )
    );
    btn.addEventListener("click", () => {
      player.currentTime = Number(btn.dataset.ms) / 1000;
      player.play().catch(() => {});
    });
    li.appendChild(btn);
    timeline.appendChild(li);
  }
}

function renderChips() {
  chips.innerHTML = "";
  for (const q of QUICK) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = q;
    btn.addEventListener("click", () => runSearch(q));
    chips.appendChild(btn);
  }
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    credentials: "include",
    ...options,
    headers: {
      ...(options.headers || {}),
    },
  });
  return res;
}

async function loadGames() {
  const res = await api(`/api/portal/games?team_code=${encodeURIComponent(session.team_code)}`);
  if (res.status === 401) {
    showGate();
    return;
  }
  const data = await res.json();
  const games = data.games || [];
  gameList.innerHTML = "";
  for (const g of games) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.id = String(g.id);
    const opp = document.createElement("span");
    opp.className = "opp";
    opp.textContent = `vs ${g.opponent}`;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = `${g.status} · ${g.event_count} events`;
    btn.appendChild(opp);
    btn.appendChild(meta);
    btn.addEventListener("click", () => openGame(Number(btn.dataset.id), btn));
    li.appendChild(btn);
    gameList.appendChild(li);
  }
  if (games.length) {
    const first = gameList.querySelector("button");
    openGame(games[0].id, first);
  } else {
    gameTitle.textContent = "No games yet — record one from Field Ops";
  }
}

async function openGame(id, btn) {
  gameList.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  const res = await api(`/api/portal/games/${id}`);
  if (!res.ok) return;
  currentGame = await res.json();
  gameTitle.textContent = `vs ${currentGame.opponent}`;
  if (currentGame.video_path) {
    // Same-origin cookie auth works for <video> when credentials were established.
    player.src = currentGame.video_path;
  } else {
    player.removeAttribute("src");
  }
  renderTimeline(currentGame.events || []);
}

async function runSearch(q) {
  if (!currentGame) return;
  const res = await api(
    `/api/portal/search?q=${encodeURIComponent(q)}&game_id=${currentGame.id}`
  );
  if (!res.ok) return;
  const data = await res.json();
  renderTimeline(data.results || []);
  gameTitle.textContent = `vs ${currentGame.opponent} · “${q}” (${(data.results || []).length})`;
}

loginForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(loginForm);
  gateMsg.textContent = "Signing in…";
  try {
    const res = await api("/api/portal/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: fd.get("username"),
        password: fd.get("password"),
        team_code: fd.get("team_code"),
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Login failed");
    session = data;
    localStorage.setItem("soccersnap_watch_user", JSON.stringify(session));
    showApp();
    renderChips();
    await loadGames();
  } catch (err) {
    gateMsg.textContent = err.message;
  }
});

searchForm.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const q = new FormData(searchForm).get("q");
  runSearch(String(q || ""));
});

logoutBtn.addEventListener("click", async () => {
  await api("/api/portal/logout", { method: "POST" });
  localStorage.removeItem("soccersnap_watch_user");
  session = null;
  showGate();
});

(async function boot() {
  renderChips();
  // Prefer server session; fall back to probing /me
  const me = await api("/api/portal/me");
  if (me.ok) {
    session = await me.json();
    localStorage.setItem("soccersnap_watch_user", JSON.stringify(session));
    showApp();
    await loadGames();
    return;
  }
  const raw = localStorage.getItem("soccersnap_watch_user");
  if (raw) {
    // Stale client cache without cookie — force re-login
    localStorage.removeItem("soccersnap_watch_user");
  }
})();

// silence unused helper when not used for innerHTML paths
void escapeHtml;
