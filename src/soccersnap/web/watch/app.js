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

function renderTimeline(events) {
  timeline.innerHTML = events
    .map(
      (e) => `
      <li>
        <button type="button" data-ms="${e.t_start_ms}">
          <span class="t">${fmt(e.t_start_ms)}</span>
          ${e.label || e.type}${e.jersey_number ? ` · #${e.jersey_number}` : ""}
        </button>
      </li>`
    )
    .join("");
  timeline.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      player.currentTime = Number(btn.dataset.ms) / 1000;
      player.play().catch(() => {});
    });
  });
}

function renderChips() {
  chips.innerHTML = QUICK.map((q) => `<button type="button" data-q="${q}">${q}</button>`).join("");
  chips.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => runSearch(btn.dataset.q));
  });
}

async function loadGames() {
  const res = await fetch(`/api/portal/games?team_code=${encodeURIComponent(session.team_code)}`);
  const data = await res.json();
  const games = data.games || [];
  gameList.innerHTML = games
    .map(
      (g) => `
      <li>
        <button type="button" data-id="${g.id}">
          <span class="opp">vs ${g.opponent}</span>
          <span class="meta">${g.status} · ${g.event_count} events</span>
        </button>
      </li>`
    )
    .join("");
  gameList.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => openGame(Number(btn.dataset.id), btn));
  });
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
  const res = await fetch(`/api/portal/games/${id}`);
  currentGame = await res.json();
  gameTitle.textContent = `vs ${currentGame.opponent}`;
  if (currentGame.video_path) {
    player.src = currentGame.video_path;
  } else {
    player.removeAttribute("src");
  }
  renderTimeline(currentGame.events || []);
}

async function runSearch(q) {
  if (!currentGame) return;
  const res = await fetch(
    `/api/portal/search?q=${encodeURIComponent(q)}&game_id=${currentGame.id}`
  );
  const data = await res.json();
  renderTimeline(data.results || []);
  gameTitle.textContent = `vs ${currentGame.opponent} · “${q}” (${(data.results || []).length})`;
}

loginForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const fd = new FormData(loginForm);
  gateMsg.textContent = "Signing in…";
  try {
    const res = await fetch("/api/portal/login", {
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
    localStorage.setItem("soccersnap_session", JSON.stringify(session));
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

logoutBtn.addEventListener("click", () => {
  localStorage.removeItem("soccersnap_session");
  session = null;
  showGate();
});

(async function boot() {
  renderChips();
  const raw = localStorage.getItem("soccersnap_session");
  if (!raw) return;
  try {
    session = JSON.parse(raw);
    showApp();
    await loadGames();
  } catch {
    localStorage.removeItem("soccersnap_session");
  }
})();
