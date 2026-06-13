const down = new Set();
const valid = ["w", "a", "s", "d"];
const CONTROL_MS = 20;
const $ = id => document.getElementById(id);
const power = $("power");
const cv = $("overlay");
const ctx = cv.getContext("2d");

let lockOn = false;
let lockOdo = false;
let lastState = {};
let driveSeq = Date.now() * 1000;

function keys(){ return valid.filter(k => down.has(k)).join("") }
function drivePayload(){ return {keys: keys(), power: +power.value, seq: ++driveSeq} }

function paintKeys(){
  for(const k of valid) $("h" + k).classList.toggle("on", down.has(k));
  $("powerOut").textContent = power.value + "%";
}

async function post(path, data, signal){
  const r = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data),
    signal,
  });
  const out = await r.json().catch(() => ({}));
  if(!r.ok) out.error = out.error || `HTTP ${r.status}`;
  return out;
}

function frameSize(s){
  const [w, h] = (s.camera?.size || "1296x972").split("x").map(Number);
  return [w || 1296, h || 972];
}

function drawBox(d, style, label){
  const [fw, fh] = frameSize(lastState);
  const scale = Math.min(cv.width / fw, cv.height / fh);
  const dw = fw * scale, dh = fh * scale;
  const ox = (cv.width - dw) / 2, oy = (cv.height - dh) / 2;
  const [x1, y1, x2, y2] = d.box;
  const x = ox + x1 * dw, y = oy + y1 * dh;
  const w = (x2 - x1) * dw, h = (y2 - y1) * dh;

  ctx.setLineDash(style.dash || []);
  ctx.lineWidth = style.width || 2;
  ctx.strokeStyle = style.stroke;
  ctx.fillStyle = style.fill;
  ctx.strokeRect(x, y, w, h);

  const t = label(d);
  const ty = Math.max(0, y - 22);
  const tw = Math.min(cv.width - x, ctx.measureText(t).width + 10);
  ctx.fillRect(x, ty, tw, 22);
  ctx.fillStyle = style.text;
  ctx.fillText(t, x + 5, ty + 3);
  ctx.setLineDash([]);
}

function drawOverlay(s){
  lastState = s;
  cv.width = innerWidth;
  cv.height = innerHeight;
  ctx.clearRect(0, 0, cv.width, cv.height);

  if(!$("showDetections").checked) return;

  const lock = s.skill_runner?.lock_on_odometric?.running
    ? s.skill_runner.lock_on_odometric
    : (s.skill_runner?.lock_on || {});

  if(lock.running && lock.box){
    ctx.lineWidth = 3;
    ctx.font = "14px system-ui";
    ctx.textBaseline = "top";
    drawBox(lock, {stroke:"#22c55e", fill:"#052e16dd", text:"#dcfce7", width:3},
      d => `lock off ${d.offset ?? 0} turn ${d.turn ?? 0}`);
    return;
  }

  if(!["idle", "manual"].includes(s.control?.mode || "idle")) return;

  const p = s.perception || {};
  const tracks = p.tracks || [];
  const det = p.detections || [];

  ctx.lineWidth = 3;
  ctx.font = "14px system-ui";
  ctx.textBaseline = "top";

  for(const d of det){
    drawBox(d, {stroke:"#60a5fa", fill:"#07152bdd", text:"#dbeafe", dash:[8,5], width:2},
      d => `${d.label} pc ${Math.round((d.score || 0) * 100)}%`);
  }

  for(const t of tracks){
    drawBox(t, {stroke:"#22d3ee", fill:"#061a1ddd", text:"#cffafe", width:3},
      d => `${d.label} track q${Math.round((d.quality || 0) * 100)} ${d.age?.toFixed?.(1) ?? "?"}s`);
  }
}

function paintHud(s){
  const c = s.control || {};
  const ks = new Set(c.keys || "");
  $("mode").textContent = c.mode || "idle";
  for(const k of valid) $("h" + k).classList.toggle("on", ks.has(k) || down.has(k));
}

function paintVision(p = {}){
  const age = p.age == null ? "no feed" : `${Number(p.age).toFixed(1)}s ago`;
  const infer = p.latency?.infer_ms == null ? "?" : `${Math.round(Number(p.latency.infer_ms))}ms`;
  $("vision").textContent = `${p.model || p.backend || "none"} · ${p.fresh ? "fresh" : "stale"} · ${age} · infer ${infer}`;
}

function paintOdometry(o = {}){
  const rad = Number(o.rad_s || 0);
  const score = o.score == null ? "" : ` · q${Math.round(Number(o.score) * 100)}%`;
  $("odo").textContent = `${rad.toFixed(2)} rad/s · ${o.fresh ? "fresh" : "stale"}${score}`;
}

function paintSkillState(s){
  const lock = s.skill_runner?.lock_on || {};
  const odo = s.skill_runner?.lock_on_odometric || {};
  lockOn = !!lock.running;
  lockOdo = !!odo.running;

  const b = $("lockBtn");
  if(b){
    b.textContent = lockOn ? "Stop Lock" : "Lock";
    b.classList.toggle("on", lockOn);
  }

  const ob = $("lockOdoBtn");
  if(ob){
    ob.textContent = lockOdo ? "Stop Odo" : "Odo Lock";
    ob.classList.toggle("on", lockOdo);
  }

  const input = $("lockTarget");
  if(input){
    input.disabled = lockOn || lockOdo;
    if(lock.running && lock.target) input.value = lock.target;
    if(odo.running && odo.target) input.value = odo.target;
  }
}

function applyState(s){
  if(!s.motion) return;

  $("left").textContent = s.motion.left + "%";
  $("right").textContent = s.motion.right + "%";

  const c = s.camera.settings;
  const p = s.perception || {};

  $("crop").value = c.crop;
  $("hflip").checked = !!c.hflip;
  $("vflip").checked = !!c.vflip;
  $("cropOut").textContent = c.crop + "%";

  paintVision(p);
  paintOdometry(s.odometry || {});

  const err = [s.camera.error, p.error].filter(Boolean).join("\n");
  $("err").textContent = err;
  $("err").classList.toggle("hide", !err);

  paintHud(s);
  paintSkillState(s);
  drawOverlay(s);
}

function applyDriveState(s){
  if(!s.motion) return;
  $("left").textContent = s.motion.left + "%";
  $("right").textContent = s.motion.right + "%";
  if(s.control) paintHud(s);
  if(s.stale) showError(`stale drive command; resyncing seq ${s.seq ?? ""}`);
}

async function toggleLockTarget(kind = "normal"){
  const target = ($("lockTarget")?.value || "person").trim() || "person";
  const running = lockOn || lockOdo;
  const path = running
    ? "/skill/stop"
    : (kind === "odometric" ? "/skill/lock-on-odometric" : "/skill/lock-on");

  const r = await post(path, {target});
  lockOn = !running && kind !== "odometric" && r.ok !== false;
  lockOdo = !running && kind === "odometric" && r.ok !== false;

  const b = $("lockBtn");
  if(b){
    b.textContent = lockOn ? "Stop Lock" : "Lock";
    b.classList.toggle("on", lockOn);
  }

  const ob = $("lockOdoBtn");
  if(ob){
    ob.textContent = lockOdo ? "Stop Odo" : "Odo Lock";
    ob.classList.toggle("on", lockOdo);
  }

  const input = $("lockTarget");
  if(input) input.disabled = lockOn || lockOdo;
}

let driveInFlight = false;
let driveDirty = false;
let driveAbort = null;
let lastDriveAt = 0;

function showError(msg){
  $("err").textContent = msg || "";
  $("err").classList.toggle("hide", !msg);
}

async function sendDrive(force = false){
  paintKeys();

  if(driveInFlight){
    driveDirty = true;
    if(force && driveAbort) driveAbort.abort();
    else return;
  }

  const wait = Math.max(0, CONTROL_MS - (performance.now() - lastDriveAt));
  if(wait && !force) await new Promise(r => setTimeout(r, wait));

  driveInFlight = true;
  driveDirty = false;
  driveAbort = new AbortController();
  lastDriveAt = performance.now();

  try{
    const out = await post("/drive", drivePayload(), driveAbort.signal);
    if(out.stale){
      driveSeq = Date.now() * 1000;
      driveDirty = true;
    }
    applyDriveState(out);
    if(out.error) showError(out.error);
  }catch(e){
    if(e.name !== "AbortError"){
      showError(e.message || String(e));
      driveDirty = true;
    }
  }finally{
    driveInFlight = false;
    driveAbort = null;
    if(driveDirty) sendDrive();
  }
}

async function stopNow(){
  down.clear();
  paintKeys();
  await post("/skill/stop", {});
  await post("/motion/stop", {});
}

async function settings(){
  const data = {
    crop: +$("crop").value,
    hflip: $("hflip").checked,
    vflip: $("vflip").checked,
  };
  $("cropOut").textContent = data.crop + "%";
  applyState(await post("/camera/settings", data));
}

async function loadEmotes(){
  const sel = $("emoteSelect");
  if(!sel) return;

  const data = await fetch("/api/emotes").then(r => r.json()).catch(() => ({
    emotes: ["nod", "shake", "wiggle", "backoff"],
  }));

  sel.innerHTML = "";
  const first = document.createElement("option");
  first.value = "";
  first.textContent = "Emote…";
  sel.appendChild(first);

  for(const name of data.emotes || []){
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    sel.appendChild(opt);
  }
}

async function runEmote(name){
  if(!name) return;

  down.clear();
  paintKeys();

  await post("/skill/stop", {});
  const out = await post("/skill/emote", {name});
  showError(out.error || "");

  fetch("/api/state").then(r => r.json()).then(applyState);
}

function isTyping(e){
  return ["INPUT", "TEXTAREA", "SELECT"].includes(e.target?.tagName);
}

window.addEventListener("keydown", e => {
  if(isTyping(e)) return;
  const k = e.code?.slice(3).toLowerCase();
  if(valid.includes(k)){
    e.preventDefault();
    if(!down.has(k)){
      down.add(k);
      sendDrive();
    }
  }
});

window.addEventListener("keyup", e => {
  if(isTyping(e)) return;
  const k = e.code?.slice(3).toLowerCase();
  if(valid.includes(k)){
    e.preventDefault();
    down.delete(k);
    sendDrive();
  }
});

window.addEventListener("blur", stopNow);
power.addEventListener("input", sendDrive);

for(const id of ["crop", "hflip", "vflip"]){
  $(id).addEventListener("input", settings);
}

$("showDetections").addEventListener("input", () =>
  fetch("/api/state").then(r => r.json()).then(applyState)
);

$("lockTarget").addEventListener("keydown", e => {
  if(e.key === "Enter"){
    e.preventDefault();
    if(!lockOn) toggleLockTarget();
  }
});

$("lockTarget").addEventListener("focus", () => {
  $("mode").textContent = "typing";
  showError("typing target; WASD disabled");
});

$("lockTarget").addEventListener("blur", () => showError(""));

$("emoteSelect").addEventListener("change", e => {
  const name = e.target.value;
  e.target.value = "";
  runEmote(name);
});

setInterval(() => { if(down.size) sendDrive() }, CONTROL_MS);
setInterval(() => fetch("/api/state").then(r => r.json()).then(applyState), 350);
setInterval(() => fetch("/api/odometry").then(r => r.json()).then(paintOdometry).catch(() => {}), 150);

fetch("/api/state").then(r => r.json()).then(applyState);
loadEmotes();
document.querySelector("main").focus();
paintKeys();
