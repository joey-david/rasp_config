#!/usr/bin/env python3
"""Thin web cockpit. No GPIO, no motor mapping, no movement math."""
import json, signal, subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from robot_api import robot

PAGE = r'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Robot Driver</title><style>
*{box-sizing:border-box}body{margin:0;background:#050505;color:#f7f7fb;font-family:system-ui,sans-serif;overflow:hidden}.stream,#overlay{position:fixed;inset:0;width:100vw;height:100vh;object-fit:cover;background:#000}.stream{z-index:0}#overlay{z-index:1;background:transparent;pointer-events:none}.shade{position:fixed;inset:0;z-index:2;background:linear-gradient(180deg,rgba(0,0,0,.2),transparent 40%,rgba(0,0,0,.65));pointer-events:none}.bar{position:fixed;z-index:3;left:12px;right:12px;bottom:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;padding:12px;border:1px solid #ffffff24;border-radius:22px;background:#080a0dcc;backdrop-filter:blur(18px);box-shadow:0 18px 60px #0009}.brand{font-weight:850;min-width:120px}.muted{font-size:12px;color:#b8bac4}.group{display:flex;gap:8px;align-items:center;padding:8px 10px;border-radius:16px;background:#ffffff14}.stat{min-width:58px}.label{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:#b8bac4}.value{font-weight:800;font-size:13px}button{border:0;border-radius:14px;height:38px;padding:0 14px;font-weight:850}.danger{background:#fb7185;color:#1b0205}.recording{background:#f43f5e;color:white}.key{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:9px;background:#ffffff18;color:#b8bac4;font-size:12px;font-weight:850}.on{background:#f7f7fb;color:#080a0d}.hud{position:fixed;z-index:3;top:12px;left:12px;display:grid;grid-template-columns:28px 28px 28px;gap:5px;padding:8px;border:1px solid #ffffff24;border-radius:16px;background:#080a0dcc}.hud .mode{grid-column:1/4;text-align:center;font-size:11px;color:#b8bac4;text-transform:uppercase;font-weight:850}.hud .spacer{visibility:hidden}input{accent-color:white}.pill{font-size:12px;color:#d7dae5;max-width:320px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.err{flex-basis:100%;font:12px ui-monospace,monospace;color:#fecdd3;white-space:pre-wrap}.hide{display:none}@media(max-width:760px){.bar{max-height:45vh;overflow:auto}}
</style><img id="stream" class="stream" src="/stream.mjpg"><canvas id="overlay"></canvas><div class="shade"></div><div class="hud" aria-label="drive state"><div id="mode" class="mode">idle</div><span></span><span id="hw" class="key">W</span><span></span><span id="ha" class="key">A</span><span id="hs" class="key">S</span><span id="hd" class="key">D</span></div><main class="bar" tabindex="0">
<div><div class="brand">Robot Driver</div><div id="status" class="muted">booting</div></div>
<div class="group"><span class="stat"><span class="label">Keys</span><span id="keys" class="value">none</span></span><span id="kw" class="key">W</span><span id="ka" class="key">A</span><span id="ks" class="key">S</span><span id="kd" class="key">D</span></div>
<label class="group"><span class="stat"><span class="label">Power</span><span id="powerOut" class="value">50%</span></span><input id="power" type="range" min="0" max="100" value="50"></label>
<div class="group"><span class="stat"><span class="label">Left</span><span id="left" class="value">0</span></span><span class="stat"><span class="label">Right</span><span id="right" class="value">0</span></span></div>
<label class="group"><span class="stat"><span class="label">FPS</span><span id="fpsOut" class="value">30</span></span><input id="fps" type="range" min="1" max="30" value="30"></label>
<label class="group"><span class="stat"><span class="label">Crop</span><span id="cropOut" class="value">0%</span></span><input id="crop" type="range" min="0" max="75" value="0"></label>
<label class="group"><input id="hflip" type="checkbox"> H flip</label><label class="group"><input id="vflip" type="checkbox"> V flip</label>
<label class="group"><input id="showDetections" type="checkbox" checked> Detections</label>
<div class="group pill"><span class="label">Vision</span>&nbsp;<span id="vision">waiting</span></div>
<div class="group pill"><span class="label">Seen</span>&nbsp;<span id="seen">none</span></div>
<div class="group pill"><span class="label">Map</span>&nbsp;<span id="map">empty</span></div>
<div class="group pill"><span class="label">Memory</span>&nbsp;<span id="memory">empty</span></div>
<button id="record" data-action="record" onclick="toggleRecord()">Record</button><button class="danger" onclick="stopNow()">Stop</button><button onclick="document.documentElement.requestFullscreen?.()">Full</button><div id="err" class="err hide"></div>
</main><script>
const down=new Set(), valid=["w","a","s","d"], $=id=>document.getElementById(id), power=$("power"), cv=$("overlay"), ctx=cv.getContext("2d"), recorder="http://127.0.0.1:8765";
let recording=false;
function keys(){return valid.filter(k=>down.has(k)).join("")}
function paintKeys(){const s=keys();$("keys").textContent=s||"none";for(const k of valid)$("k"+k).classList.toggle("on",down.has(k));$("powerOut").textContent=power.value+"%"}
async function post(path,data){const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});return r.json().catch(()=>({}))}
function frameSize(s){const [w,h]=(s.camera?.size||"1296x972").split("x").map(Number);return [w||1296,h||972]}
function drawOverlay(s){cv.width=innerWidth;cv.height=innerHeight;ctx.clearRect(0,0,cv.width,cv.height);if(!$("showDetections").checked)return;const p=s.perception||{},det=p.detections||[],fresh=!!p.fresh,[fw,fh]=frameSize(s),scale=Math.max(cv.width/fw,cv.height/fh),dw=fw*scale,dh=fh*scale,ox=(cv.width-dw)/2,oy=(cv.height-dh)/2;ctx.lineWidth=3;ctx.font="14px system-ui";ctx.textBaseline="top";for(const d of det){const [x1,y1,x2,y2]=d.box,x=ox+x1*dw,y=oy+y1*dh,w=(x2-x1)*dw,h=(y2-y1)*dh,age=d.received_at?Math.max(0,Date.now()/1000-d.received_at):p.age,t=`${d.label} ${Math.round((d.score||0)*100)}% · ${d.bearing_deg??"?"}° · ${d.distance_proxy??"?"} · ${age==null?"?":age.toFixed(1)+"s"}`;ctx.strokeStyle=fresh?"#7dd3fc":"#fbbf24";ctx.fillStyle=fresh?"#071018dd":"#211804dd";ctx.strokeRect(x,y,w,h);const tw=ctx.measureText(t).width+10;ctx.fillRect(x,Math.max(0,y-22),tw,22);ctx.fillStyle=fresh?"#e0f2fe":"#fef3c7";ctx.fillText(t,x+5,Math.max(0,y-19))}}
function paintHud(s){const c=s.control||{},ks=new Set(c.keys||"");$("mode").textContent=c.mode||"idle";for(const k of valid){$("h"+k).classList.toggle("on",ks.has(k));$("k"+k).classList.toggle("on",down.has(k)||ks.has(k))}}
function applyState(s){if(!s.motion)return;$("left").textContent=s.motion.left+"%";$("right").textContent=s.motion.right+"%";$("status").textContent=s.motion.direction+" · "+s.motion.speed+"%";const c=s.camera.settings,p=s.perception||{};$("fps").value=c.fps;$("crop").value=c.crop;$("hflip").checked=!!c.hflip;$("vflip").checked=!!c.vflip;$("fpsOut").textContent=c.fps;$("cropOut").textContent=c.crop+"%";const det=p.detections||[],mem=s.memory?.inventory||[],map=p.map||[],age=p.age==null?"no feed":p.age.toFixed(1)+"s",lat=p.latency?.infer_ms;$("vision").textContent=`${p.model||p.backend||"none"} · ${p.fresh?"fresh":"stale"} · ${age}${lat?` · infer ${lat}ms`:""}`;$("seen").textContent=det.map(d=>`${d.label}${d.score?` ${Math.round(d.score*100)}%`:""}`).slice(0,6).join(", ")||"none";$("map").textContent=map.map(x=>`${x.label} ${x.bearing_deg}°/${x.distance_proxy}`).slice(0,6).join(", ")||"empty";$("memory").textContent=[...new Set(mem.map(x=>x.label))].slice(0,8).join(", ")||"empty";const err=[s.camera.error,p.error].filter(Boolean).join("\n");$("err").textContent=err;$("err").classList.toggle("hide",!err);paintHud(s);drawOverlay(s)}
async function toggleRecord(){try{const path=recording?"/stop":"/start",r=await fetch(recorder+path,{method:"POST"}),j=await r.json();recording=!!j.recording;$("record").textContent=recording?"Stop Rec":"Record";$("record").classList.toggle("recording",recording);if(j.path)$("status").textContent=j.path}catch(e){$("err").textContent="Recorder offline: run bin/record-server";$("err").classList.remove("hide")}}
async function drive(){paintKeys();applyState(await post("/drive",{keys:keys(),power:+power.value}))}
async function stopNow(){down.clear();await drive()}
async function settings(){const data={fps:+$("fps").value,crop:+$("crop").value,hflip:$("hflip").checked,vflip:$("vflip").checked};$("fpsOut").textContent=data.fps;$("cropOut").textContent=data.crop+"%";applyState(await post("/camera/settings",data))}
window.addEventListener("keydown",e=>{const k=e.code?.slice(3).toLowerCase();if(valid.includes(k)){e.preventDefault();if(!down.has(k)){down.add(k);drive()}}});
window.addEventListener("keyup",e=>{const k=e.code?.slice(3).toLowerCase();if(valid.includes(k)){e.preventDefault();down.delete(k);drive()}});
window.addEventListener("blur",stopNow);power.addEventListener("input",drive);$("showDetections").addEventListener("input",()=>fetch("/api/state").then(r=>r.json()).then(applyState));for(const id of ["fps","crop","hflip","vflip"])$(id).addEventListener("input",settings);setInterval(()=>{if(down.size)drive()},100);setInterval(()=>fetch("/api/state").then(r=>r.json()).then(applyState),350);fetch(recorder+"/status").then(r=>r.json()).then(j=>{recording=!!j.recording;$("record").textContent=recording?"Stop Rec":"Record";$("record").classList.toggle("recording",recording)}).catch(()=>{});fetch("/api/state").then(r=>r.json()).then(applyState);document.querySelector("main").focus();paintKeys();
</script>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def body(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        try: return json.loads(self.rfile.read(n).decode() or "{}")
        except Exception: return {}

    def send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)): body = json.dumps(body).encode()
        elif isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items(): self.send_header(k, str(v))
        self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        p, b = urlparse(self.path).path, self.body()
        if p == "/drive": return self.send(200, robot.drive_keys(b.get("keys", ""), b.get("power")))
        if p == "/motion/stop": return self.send(200, robot.stop())
        if p == "/camera/settings": robot.camera.apply_settings(**b); return self.send(200, robot.status())
        if p == "/api/perception/detections": return self.send(200, robot.ingest_detections(b))
        if p == "/skill/goto": return self.send(200, robot.goto(b.get("target", "")))
        if p == "/skill/push": return self.send(200, robot.push(b.get("target", "")))
        self.send_error(404)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/": return self.send(200, PAGE, "text/html; charset=utf-8")
        if p == "/api/state": return self.send(200, robot.status())
        if p == "/api/detections": return self.send(200, robot.perception.status())
        if p == "/api/memory": return self.send(200, robot.memory.inventory())
        if p == "/snapshot.jpg":
            frame = robot.snapshot(); return self.send(200, frame, "image/jpeg", {"X-Captured-At": robot.camera.frame_at}) if frame else self.send_error(503, "No frame")
        if p == "/stream.mjpg": return self.stream()
        if p == "/health":
            r = subprocess.run(["rpicam-hello", "--list-cameras"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15)
            return self.send(200 if r.returncode == 0 else 503, (("ok\n" if r.returncode == 0 else "fail\n") + r.stdout.decode()), "text/plain; charset=utf-8")
        self.send_error(404)

    def stream(self):
        self.send_response(200); self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame"); self.send_header("Cache-Control", "no-store"); self.end_headers()
        for frame in robot.camera.frames():
            try:
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n" + f"Content-Length: {len(frame)}\r\n\r\n".encode() + frame + b"\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError): return


def shutdown(*_):
    robot.close(); raise SystemExit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown); signal.signal(signal.SIGTERM, shutdown)
    robot.start()
    try: ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
    finally: robot.close()
