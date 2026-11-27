const down = new Set();
const valid = ["w", "a", "s", "d"];
const CONTROL_MS = 20;
const $ = id => document.getElementById(id);
const power = $("power");
const cv = $("overlay");
const ctx = cv.getContext("2d");

let lockOn = false;
let findRunning = false;
let followRunning = false;
let procedureRunning = false;
let procedures = [];
let level2Running = false;
let autonomyRunning = false;
let lastState = {};
let lastSkillDebug = "";
let driveSeq = Date.now() * 1000;

function keys(){ return valid.filter(k => down.has(k)).join("") }
function drivePayload(){ return {keys: keys(), power: +power.value, seq: ++driveSeq} }

function debugLog(event, data = {}){
  const payload = {
    at: new Date().toISOString(),
    ...data,
  };
  console.log(`[mischief] ${event}`, payload);
}

function paintKeys(){
  for(const k of valid) $("h" + k).classList.toggle("on", down.has(k));
  $("powerOut").textContent = power.value + "%";
}

async function post(path, data, signal){
  const started = performance.now();
  const r = await fetch(path, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data),
    signal,
  });
  const out = await r.json().catch(() => ({}));
  if(!r.ok) out.error = out.error || `HTTP ${r.status}`;
  if(path.startsWith("/skill/")){
    debugLog("skill:response", {
      path,
      request: data,
      status: r.status,
      ms: Math.round(performance.now() - started),
      response: out,
    });
  }
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

  ctx.save();
  ctx.lineWidth = style.width || 2;
  ctx.strokeStyle = style.stroke;

  if(style.dash){
    ctx.setLineDash(style.dash);
    ctx.strokeRect(x, y, w, h);
    ctx.setLineDash([]);
  }else{
    // Subtle translucent fill + crisp corner-bracket reticle.
    ctx.fillStyle = style.tint || "rgba(34,211,238,0.06)";
    ctx.fillRect(x, y, w, h);
    const arm = Math.max(10, Math.min(22, Math.min(w, h) * 0.22));
    ctx.beginPath();
    ctx.moveTo(x, y + arm); ctx.lineTo(x, y); ctx.lineTo(x + arm, y);
    ctx.moveTo(x + w - arm, y); ctx.lineTo(x + w, y); ctx.lineTo(x + w, y + arm);
    ctx.moveTo(x + w, y + h - arm); ctx.lineTo(x + w, y + h); ctx.lineTo(x + w - arm, y + h);
    ctx.moveTo(x + arm, y + h); ctx.lineTo(x, y + h); ctx.lineTo(x, y + h - arm);
    ctx.stroke();
  }

  const t = label(d);
  ctx.font = "600 12px ui-monospace, SFMono-Regular, Menlo, monospace";
  ctx.textBaseline = "middle";
  const padX = 8, ph = 22;
  const tw = Math.min(cv.width - x, ctx.measureText(t).width + padX * 2);
  const ty = Math.max(6, y - ph - 6);
  ctx.fillStyle = style.fill;
  ctx.beginPath();
  if(ctx.roundRect) ctx.roundRect(x, ty, tw, ph, 7);
  else ctx.rect(x, ty, tw, ph);
  ctx.fill();
  ctx.lineWidth = 1;
  ctx.strokeStyle = style.stroke;
  ctx.stroke();
  ctx.fillStyle = style.text;
  ctx.fillText(t, x + padX, ty + ph / 2);
  ctx.restore();
}

function drawOverlay(s){
  lastState = s;
  cv.width = innerWidth;
  cv.height = innerHeight;
  ctx.clearRect(0, 0, cv.width, cv.height);

  if(!$("showDetections").checked) return;

  const lock = s.skill_runner?.lock_on || {};
  const find = s.skill_runner?.find || {};
  const follow = s.skill_runner?.follow || {};

  if(lock.running && lock.box){
    ctx.lineWidth = 3;
    ctx.font = "14px system-ui";
    ctx.textBaseline = "top";
    drawBox(lock, {stroke:"#22c55e", fill:"#052e16dd", text:"#dcfce7", width:3},
      d => `lock off ${d.offset ?? 0} turn ${d.turn ?? 0}`);
    return;
  }

  if(find.running && find.box){
    ctx.lineWidth = 3;
    ctx.font = "14px system-ui";
    ctx.textBaseline = "top";
    drawBox(find, {stroke:"#f59e0b", fill:"#2b1703dd", text:"#ffedd5", width:3},
      d => `find off ${d.offset ?? 0}`);
    return;
  }

  if(follow.running && follow.box){
    ctx.lineWidth = 3;
    ctx.font = "14px system-ui";
    ctx.textBaseline = "top";
    const blocked = follow.phase === "blocked" || !!follow.veto;
    drawBox(
      follow,
      blocked
        ? {stroke:"#ef4444", fill:"#450a0add", text:"#fee2e2", width:3}
        : {stroke:"#a78bfa", fill:"#1f123add", text:"#ede9fe", width:3},
      d => blocked
        ? `follow blocked: ${d.veto || "safety veto"}`
        : `follow fwd ${d.linear ?? 0} turn ${d.turn ?? 0}`
    );
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
  const age = p.age == null ? "no feed" : `${Number(p.age).toFixed(1)}s`;
  const infer = p.latency?.infer_ms == null ? "?" : `${Math.round(Number(p.latency.infer_ms))}ms`;
  $("vision").textContent = `${p.model || p.backend || "none"} · ${infer} · ${age}`;
  const dot = $("visionDot");
  if(dot) dot.className = `dot ${p.fresh ? "ok" : p.error ? "danger" : "warn"}`;
}

function paintSafetyBadge(s = {}){
  const badge = $("safetyBadge");
  const text = $("safetyText");
  if(!badge || !text) return;
  const safety = s.safety || s.layers?.level0 || {};
  const edge = safety.edge || {};
  const veto = (s.skill_runner?.follow?.running && s.skill_runner?.follow?.veto) || safety.last_veto || "";
  let cls = "ok";
  let label = "Safe";
  if(edge.enabled === false){
    cls = "warn";
    label = "Safety off";
  }else if(veto || edge.danger){
    cls = "danger";
    label = veto || edge.reason || "Edge";
  }else if(!edge.ready){
    cls = "warn";
    label = edge.reason || "Calibrating";
  }
  badge.className = `status-pill ${cls}`;
  const dot = badge.querySelector(".dot");
  if(dot) dot.className = `dot ${cls}`;
  text.textContent = label;
}

function paintOdometry(o = {}){
  const rad = Number(o.rad_s || 0);
  const score = o.score == null ? "" : ` · q${Math.round(Number(o.score) * 100)}%`;
  $("odo").textContent = `${rad.toFixed(2)} rad/s · ${o.fresh ? "fresh" : "stale"}${score}`;
}

function paintPowerGauge(g = {}){
  const el = $("minPower");
  if(!el) return;
  const turn = g.min_turn ?? 35;
  const fwd = g.min_forward ?? turn;
  el.textContent = turn === fwd ? `${turn}%` : `T${turn}% / F${fwd}%`;
  const btn = $("gaugeBtn");
  if(btn) btn.disabled = !!g.running;
}

function toggleDrawer(id){
  for(const [panelId, btnId] of [["drawer", "menuToggleBtn"], ["procPanel", "procToggleBtn"]]){
    const el = $(panelId);
    const btn = $(btnId);
    if(!el) continue;
    const open = panelId === id ? el.classList.toggle("open") : (el.classList.remove("open"), false);
    if(btn) btn.classList.toggle("active", open);
  }
}

function renderSelectedProcedure(live = {}){
  const sel = $("procSelect");
  const setupEl = $("procSetup");
  const stepsEl = $("procSteps");
  if(!sel || !setupEl || !stepsEl) return;
  const activeId = live.running && live.id ? live.id : sel.value;
  const proc = procedures.find(p => p.id === activeId) || procedures[0];
  if(!proc) return;
  if(live.running && live.id && sel.value !== live.id) sel.value = live.id;
  setupEl.textContent = proc.setup;
  stepsEl.innerHTML = "";
  const isThis = live.id === proc.id;
  proc.steps.forEach((text, i) => {
    const li = document.createElement("li");
    li.textContent = text;
    if(isThis && live.running && i === live.step_index) li.className = "active";
    else if(isThis && i < (live.step_index ?? 0)) li.className = "done";
    stepsEl.appendChild(li);
  });
}

function paintProcedure(proc = {}){
  procedureRunning = !!proc.running;
  const btn = $("procRunBtn");
  if(btn){
    btn.textContent = procedureRunning ? `Stop (${proc.step_label || "running"})` : "Run Test";
    btn.classList.toggle("danger", procedureRunning);
  }
  const sel = $("procSelect");
  if(sel) sel.disabled = procedureRunning;
  const res = $("procResult");
  if(res){
    const text = proc.running
      ? `Step ${(proc.step_index ?? 0) + 1}/${proc.step_total || 1}: ${proc.step_label || ""}`
      : (proc.summary || "").replace(/ \| /g, "\n");
    res.textContent = text;
    res.classList.toggle("hide", !text);
  }
  if(procedures.length) renderSelectedProcedure(proc);
}

async function loadProcedures(){
  const sel = $("procSelect");
  if(!sel) return;
  const data = await fetch("/api/procedures").then(r => r.json()).catch(() => ({procedures: []}));
  procedures = data.procedures || [];
  sel.innerHTML = "";
  for(const p of procedures){
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.title;
    sel.appendChild(opt);
  }
  renderSelectedProcedure(data.status || {});
}

async function toggleProcedure(){
  if(procedureRunning){
    debugLog("procedure:stop-request", {});
    await post("/skill/stop", {});
    refreshState();
    return;
  }
  const id = $("procSelect")?.value;
  if(!id) return;
  const target = currentTarget();
  debugLog("procedure:start-request", {id, target});
  const out = await post("/skill/procedure", {id, target});
  if(out.error) showError(out.error);
  refreshState();
}

function paintSkillState(s){
  const claimed = s.skill_runner?.claimed || "";
  const lock = s.skill_runner?.lock_on || {};
  const find = s.skill_runner?.find || {};
  const follow = s.skill_runner?.follow || {};
  const proc = s.skill_runner?.procedure || {};
  paintProcedure(proc);
  const level2 = s.layers?.level2 || {};
  const autonomy = s.layers?.level3?.autonomy || {};
  const debugKey = JSON.stringify({
    lock: {running: !!lock.running, phase: lock.phase, target: lock.target, seen: lock.seen, offset: lock.offset, turn: lock.turn},
    find: {
      running: !!find.running,
      phase: find.phase,
      target: find.target,
      seen: find.seen,
      cycle: find.cycle,
      precheck_seen: find.precheck_seen,
      offset: find.offset,
      turn: find.turn,
      image_size: find.image_size,
      imgsz: find.imgsz,
    },
    follow: {
      running: !!follow.running,
      phase: follow.phase,
      veto: follow.veto,
      target: follow.target,
      seen: follow.seen,
      cycle: follow.cycle,
      offset: follow.offset,
      height: follow.height,
      linear: follow.linear,
      turn: follow.turn,
    },
    level2: {running: !!level2.running, skill: level2.skill, phase: level2.phase, target: level2.target},
    autonomy: {running: !!autonomy.running, phase: autonomy.phase, step: autonomy.step, action: autonomy.action},
  });
  if(debugKey !== lastSkillDebug){
    lastSkillDebug = debugKey;
    debugLog("skill:state", {lock, find, follow, level2, autonomy});
  }
  lockOn = !!lock.running || claimed === "lock-on";
  findRunning = !!find.running || claimed === "find";
  followRunning = !!follow.running || claimed === "follow";
  level2Running = !!level2.running;
  autonomyRunning = !!autonomy.running;

  const b = $("lockBtn");
  if(b){
    b.textContent = lockOn ? "Stop Lock" : "Lock";
    b.classList.toggle("on", lockOn);
    b.setAttribute("aria-pressed", String(lockOn));
  }

  const fb = $("findBtn");
  if(fb){
    fb.textContent = findRunning ? "Stop Find" : "Find";
    fb.classList.toggle("on", findRunning);
    fb.setAttribute("aria-pressed", String(findRunning));
  }

  const followBtn = $("followBtn");
  if(followBtn){
    followBtn.textContent = followRunning ? "Stop Follow" : "Follow";
    followBtn.classList.toggle("on", followRunning);
    followBtn.setAttribute("aria-pressed", String(followRunning));
  }

  const input = $("skillTarget");
  if(input){
    input.disabled = lockOn || findRunning || followRunning || procedureRunning || level2Running || autonomyRunning;
    if(lock.running && lock.target) input.value = lock.target;
    if(find.running && find.target) input.value = find.target;
    if(follow.running && follow.target) input.value = follow.target;
  }

  for(const id of ["gotoBtn", "pushBtn", "pushToBtn"]){
    const button = $(id);
    if(button) button.disabled = procedureRunning || level2Running || autonomyRunning;
  }
  const auto = $("autonomyBtn");
  if(auto){
    auto.textContent = autonomyRunning ? "Stop" : "Start";
    auto.classList.toggle("on", autonomyRunning);
  }
}

function safetyNotice(s){
  const follow = s.skill_runner?.follow || {};
  const safety = s.safety || s.layers?.level0 || {};
  const veto = (follow.running && follow.veto) || safety.last_veto || "";
  if(veto) return `safety veto: ${veto}`;
  const edge = safety.edge || {};
  if(edge.enabled && edge.danger) return `safety: ${edge.reason || "edge danger"}`;
  return "";
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
  paintPowerGauge(s.power_gauge || {});
  paintSafetyBadge(s);

  const err = [s.camera.error, p.error, safetyNotice(s)].filter(Boolean).join("\n");
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
  const veto = safetyNotice(s);
  if(veto) showError(veto);
  if(s.stale) showError(`stale drive command; resyncing seq ${s.seq ?? ""}`);
}

function currentTarget(){
  return ($("skillTarget")?.value || "person").trim() || "person";
}

async function toggleLockTarget(){
  const target = currentTarget();
  const running = lockOn || findRunning || followRunning;
  const path = running ? "/skill/stop" : "/skill/lock-on";
  debugLog(running ? "lock:stop-request" : "lock:start-request", {target, running});
  const r = await post(path, {target});
  lockOn = !running && r.ok !== false;
  findRunning = false;
  followRunning = false;

  const b = $("lockBtn");
  if(b){
    b.textContent = lockOn ? "Stop Lock" : "Lock";
    b.classList.toggle("on", lockOn);
    b.setAttribute("aria-pressed", String(lockOn));
  }

  const input = $("skillTarget");
  if(input) input.disabled = lockOn || findRunning || followRunning;
  refreshState();
}

async function toggleFindTarget(){
  const running = lockOn || findRunning || followRunning;
  if(running){
    debugLog("find:stop-request", {lockOn, findRunning});
    const out = await post("/skill/stop", {});
    debugLog("find:stop-response", out);
    lockOn = false;
    findRunning = false;
    followRunning = false;
    refreshState();
    return;
  }

  const target = currentTarget();
  debugLog("find:start-request", {target});
  findRunning = true;
  const fb = $("findBtn");
  if(fb){
    fb.textContent = "Stop Find";
    fb.classList.add("on");
    fb.setAttribute("aria-pressed", "true");
  }
  const input = $("skillTarget");
  if(input) input.disabled = true;

  const r = await post("/skill/find", {target});
  debugLog("find:complete", {
    ok: r.ok,
    found: r.found,
    centered: r.centered,
    precheck_seen: r.precheck_seen ?? r.status?.precheck_seen,
    cycles: r.cycles,
    detection: r.detection,
    status: r.status,
  });
  findRunning = false;
  if(r.error) showError(r.error);
  refreshState();
}

async function toggleFollowTarget(){
  const running = lockOn || findRunning || followRunning;
  if(running){
    debugLog("follow:stop-request", {lockOn, findRunning, followRunning});
    const out = await post("/skill/stop", {});
    debugLog("follow:stop-response", out);
    lockOn = false;
    findRunning = false;
    followRunning = false;
    refreshState();
    return;
  }

  const target = currentTarget();
  debugLog("follow:start-request", {target});
  const r = await post("/skill/follow", {target});
  followRunning = r.ok !== false;
  if(r.error) showError(r.error);
  refreshState();
}

async function runObjectSkill(name){
  const target = currentTarget();
  debugLog(`${name}:start-request`, {target});
  level2Running = true;
  const out = await post(`/skill/${name}`, {target});
  level2Running = false;
  debugLog(`${name}:complete`, out);
  showError(out.error || "");
  refreshState();
}

async function runPowerGauge(){
  const btn = $("gaugeBtn");
  if(btn) btn.disabled = true;
  debugLog("power-gauge:start-request", {});
  const out = await post("/skill/power-gauge", {});
  debugLog("power-gauge:complete", out);
  if(btn) btn.disabled = false;
  showError(out.error || "");
  refreshState();
}

async function pushTargetTo(){
  const source = currentTarget();
  const destination = ($("pushDestination")?.value || "").trim();
  level2Running = true;
  const out = await post("/skill/push-to", {source, destination});
  level2Running = false;
  debugLog("push-to:complete", out);
  showError(out.error || "");
  refreshState();
}

async function toggleAutonomy(){
  const path = autonomyRunning ? "/autonomy/stop" : "/autonomy/start";
  const goal = ($("autonomyGoal")?.value || "").trim();
  const out = await post(path, {goal});
  autonomyRunning = !autonomyRunning && out.ok !== false;
  debugLog("autonomy:toggle", {path, response: out});
  showError(out.error || "");
  refreshState();
}

let driveInFlight = false;
let driveDirty = false;
let driveAbort = null;
let lastDriveAt = 0;

function showError(msg){
  $("err").textContent = msg || "";
  $("err").classList.toggle("hide", !msg);
  if(msg) debugLog("ui:error", {message: msg});
}

let stateFailed = false;

async function refreshState(){
  try{
    const response = await fetch("/api/state");
    if(!response.ok) throw new Error(`state HTTP ${response.status}`);
    applyState(await response.json());
    if(stateFailed) debugLog("state:restored", {});
    stateFailed = false;
  }catch(error){
    if(!stateFailed) debugLog("state:unavailable", {error: error.message || String(error)});
    stateFailed = true;
  }
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
  debugLog("stop:request", {});
  const skill = await post("/skill/stop", {});
  const motion = await post("/motion/stop", {});
  debugLog("stop:response", {skill, motion});
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

  debugLog("emote:start-request", {name});
  await post("/skill/stop", {});
  const out = await post("/skill/emote", {name});
  debugLog("emote:response", out);
  showError(out.error || "");

  refreshState();
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
  refreshState()
);

$("skillTarget").addEventListener("keydown", e => {
  if(e.key === "Enter"){
    e.preventDefault();
    if(!lockOn) toggleLockTarget();
  }
});

$("skillTarget").addEventListener("focus", () => {
  $("mode").textContent = "typing";
  showError("typing target; WASD disabled");
});

$("skillTarget").addEventListener("blur", () => showError(""));

$("emoteSelect").addEventListener("change", e => {
  const name = e.target.value;
  e.target.value = "";
  runEmote(name);
});

$("procSelect")?.addEventListener("change", () => renderSelectedProcedure(lastState.skill_runner?.procedure || {}));

setInterval(() => { if(down.size) sendDrive() }, CONTROL_MS);
setInterval(refreshState, 350);
setInterval(() => fetch("/api/odometry").then(r => r.json()).then(paintOdometry).catch(() => {}), 150);

refreshState();
loadEmotes();
loadProcedures();
document.querySelector("main").focus();
paintKeys();
