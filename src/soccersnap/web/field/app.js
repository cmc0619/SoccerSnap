const logList = document.getElementById("logList");
const camGrid = document.getElementById("camGrid");
const statusLine = document.getElementById("statusLine");
const sessionLabel = document.getElementById("sessionLabel");
const recordBtn = document.getElementById("recordBtn");
const preflightBtn = document.getElementById("preflightBtn");
const processBtn = document.getElementById("processBtn");

let recording = false;
let lastSessionId = null;
let opsKey = localStorage.getItem("soccersnap_ops_key") || "";

function opsHeaders(json = false) {
  const headers = { "X-SoccerSnap-Key": opsKey };
  if (json) headers["Content-Type"] = "application/json";
  return headers;
}

function log(msg) {
  const li = document.createElement("li");
  const ts = new Date().toLocaleTimeString();
  li.textContent = `[${ts}] ${msg}`;
  logList.prepend(li);
}

function renderCams(cameras = []) {
  camGrid.innerHTML = cameras
    .map((cam) => {
      const q = cam.framing?.quality || "good";
      return `
        <article class="cam">
          <h3>${cam.camera_id}</h3>
          <div class="meta">
            Sync ${Number(cam.offset_ms).toFixed(2)} ms<br />
            Batt ${cam.battery_percent}% · ${cam.temperature_c}°C<br />
            ${cam.recording ? "RECORDING" : "Idle"}
          </div>
          <span class="badge ${q}">${q.replace("_", " ")}</span>
        </article>
      `;
    })
    .join("");
}

async function ensureOpsKey() {
  if (opsKey) return;
  // Ops key is never public — unlock with admin basic auth (demo defaults).
  const res = await fetch("/api/demo/field-unlock", {
    method: "POST",
    headers: {
      Authorization: "Basic " + btoa("admin:soccersnap"),
    },
  });
  if (!res.ok) throw new Error("Field unlock failed — check admin credentials");
  const data = await res.json();
  opsKey = data.ops_api_key || "";
  localStorage.setItem("soccersnap_ops_key", opsKey);
}

async function refreshStatus() {
  const res = await fetch("/api/v1/coordinator/status");
  const data = await res.json();
  recording = !!data.recording;
  lastSessionId = data.session_id || lastSessionId;
  sessionLabel.textContent = lastSessionId ? `Session ${lastSessionId}` : "No active session";
  statusLine.textContent = recording
    ? "Recording — scheduled fleet is hot."
    : "Fleet idle. Preflight, then Record.";
  recordBtn.textContent = recording ? "Stop" : "Record";
  recordBtn.classList.toggle("live", recording);
  processBtn.disabled = !lastSessionId || recording;
  renderCams(data.cameras || []);
}

preflightBtn.addEventListener("click", async () => {
  preflightBtn.disabled = true;
  try {
    const res = await fetch("/api/v1/coordinator/preflight", { method: "POST" });
    const data = await res.json();
    renderCams(data.status?.cameras || []);
    if (data.ok) {
      statusLine.textContent = "Preflight clear — ready for scheduled start.";
      log("Preflight OK");
    } else {
      statusLine.textContent = `Preflight blocked: ${(data.blocking || []).map((b) => b.reason).join("; ")}`;
      log("Preflight failed");
    }
  } catch (err) {
    log(`Preflight error: ${err.message}`);
  } finally {
    preflightBtn.disabled = false;
  }
});

recordBtn.addEventListener("click", async () => {
  recordBtn.disabled = true;
  try {
    await ensureOpsKey();
    if (!recording) {
      const res = await fetch("/api/v1/coordinator/start", {
        method: "POST",
        headers: opsHeaders(true),
        body: JSON.stringify({ delay_sec: 0.4 }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail?.message || JSON.stringify(data.detail || data));
      lastSessionId = data.session_id;
      log(`Scheduled start ${data.scheduled_start} · ${data.session_id}`);
      statusLine.textContent = `Rolling at ${data.scheduled_start}`;
    } else {
      const res = await fetch("/api/v1/coordinator/stop?duration_sec=4", {
        method: "POST",
        headers: opsHeaders(),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Stop failed");
      lastSessionId = data.session_id;
      log(`Stopped ${data.session_id} · ${data.flat_manifests?.length || 0} manifests`);
      statusLine.textContent = "Stopped — ready to Process (checksum offload + stitch).";
    }
    await refreshStatus();
  } catch (err) {
    log(`Record error: ${err.message}`);
    statusLine.textContent = err.message;
  } finally {
    recordBtn.disabled = false;
  }
});

processBtn.addEventListener("click", async () => {
  if (!lastSessionId) return;
  processBtn.disabled = true;
  statusLine.textContent = "Offloading with checksum verify, stitching, tagging events…";
  try {
    await ensureOpsKey();
    const res = await fetch("/api/v1/process/from-rig", {
      method: "POST",
      headers: opsHeaders(true),
      body: JSON.stringify({ session_id: lastSessionId, opponent: "Rivals" }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Process failed");
    log(`Ready: ${data.session_id} · ${data.events} events`);
    statusLine.textContent = `Game ready — open Watch. ${data.events} events tagged.`;
    if (!document.getElementById("watchLink")) {
      processBtn.insertAdjacentHTML(
        "afterend",
        ` <a id="watchLink" class="ghost" style="display:inline-flex;align-items:center;padding:0.85rem 1.25rem;border-radius:999px;border:1px solid rgba(242,240,233,0.3);font-weight:700;" href="/watch/">Watch</a>`
      );
    }
  } catch (err) {
    log(`Process error: ${err.message}`);
    statusLine.textContent = err.message;
  } finally {
    processBtn.disabled = false;
  }
});

ensureOpsKey()
  .then(() => refreshStatus())
  .catch((err) => {
    statusLine.textContent = `Cannot reach API: ${err.message}`;
  });
setInterval(() => {
  refreshStatus().catch(() => {});
}, 4000);
