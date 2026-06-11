const down=new Set(), valid=["w","a","s","d"], CONTROL_MS=20, $=id=>document.getElementById(id), power=$("power"), cv=$("overlay"), ctx=cv.getContext("2d");
let recording=false, visionOn=true, lockOn=false, lastState={};
let driveSeq=0;

function keys(){return valid.filter(k=>down.has(k)).join("")}
function drivePayload(){return {keys:keys(), power:+power.value, seq:++driveSeq}}
function paintKeys(){for(const k of valid){$("h"+k).classList.toggle("on",down.has(k))}$("powerOut").textContent=power.value+"%"}
async function post(path,data,signal){const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data),signal});return r.json().catch(()=>({}))}
function frameSize(s){const [w,h]=(s.camera?.size||"1296x972").split("x").map(Number);return [w||1296,h||972]}

function drawBox(d, style, label){
  const [fw,fh]=frameSize(lastState), scale=Math.min(cv.width/fw,cv.height/fh), dw=fw*scale, dh=fh*scale, ox=(cv.width-dw)/2, oy=(cv.height-dh)/2;
  const [x1,y1,x2,y2]=d.box, x=ox+x1*dw, y=oy+y1*dh, w=(x2-x1)*dw, h=(y2-y1)*dh;
  ctx.setLineDash(style.dash||[]);ctx.lineWidth=style.width||2;ctx.strokeStyle=style.stroke;ctx.fillStyle=style.fill;ctx.strokeRect(x,y,w,h);
  const t=label(d), ty=Math.max(0,y-22), tw=Math.min(cv.width-x,ctx.measureText(t).width+10);
  ctx.fillRect(x,ty,tw,22);ctx.fillStyle=style.text;ctx.fillText(t,x+5,ty+3);ctx.setLineDash([]);
}

function drawOverlay(s){
  lastState=s;
  cv.width=innerWidth;cv.height=innerHeight;ctx.clearRect(0,0,cv.width,cv.height);
  if(!$("showDetections").checked)return;
  const lock=s.skill_runner?.lock_on||{};
  if(lock.running && lock.box){
    ctx.lineWidth=3;ctx.font="14px system-ui";ctx.textBaseline="top";
    drawBox(lock,{stroke:"#22c55e",fill:"#052e16dd",text:"#dcfce7",width:3},d=>`lock off ${d.offset??0} turn ${d.turn??0}`);
    return;
  }
  const p=s.perception||{}, tracks=p.tracks||[], det=p.detections||[];
  ctx.lineWidth=3;ctx.font="14px system-ui";ctx.textBaseline="top";
  for(const d of det)drawBox(d,{stroke:"#60a5fa",fill:"#07152bdd",text:"#dbeafe",dash:[8,5],width:2},d=>`${d.label} pc ${Math.round((d.score||0)*100)}%`);
  for(const t of tracks)drawBox(t,{stroke:"#22d3ee",fill:"#061a1ddd",text:"#cffafe",width:3},d=>`${d.label} track q${Math.round((d.quality||0)*100)} ${d.age?.toFixed?.(1)??"?"}s`);
}

function paintHud(s){
  const c=s.control||{}, ks=new Set(c.keys||"");
  $("mode").textContent=c.mode||"idle";
  for(const k of valid)$("h"+k).classList.toggle("on",ks.has(k)||down.has(k));
}

function paintSkillState(s){
  const lock=s.skill_runner?.lock_on||{};
  lockOn=!!lock.running;
  const b=$("lockBtn");
  if(b){b.textContent=lockOn?"Stop Lock":"Lock Person";b.classList.toggle("on",lockOn)}
}

function applyState(s){
  if(!s.motion)return;
  $("left").textContent=s.motion.left+"%";$("right").textContent=s.motion.right+"%";
  const c=s.camera.settings,p=s.perception||{};
  $("crop").value=c.crop;$("hflip").checked=!!c.hflip;$("vflip").checked=!!c.vflip;$("cropOut").textContent=c.crop+"%";
  const det=p.detections||[],tracks=p.tracks||[],age=p.age==null?"no feed":p.age.toFixed(1)+"s",lat=p.latency?.infer_ms;
  $("vision").textContent=`${p.model||p.backend||"none"} · ${p.fresh?"fresh":"stale"} · ${age}${lat?` · infer ${lat}ms`:""}`;
  $("seen").textContent=(tracks.length?tracks:det).map(d=>`${d.label}${d.quality?` q${Math.round(d.quality*100)}%`:d.score?` ${Math.round(d.score*100)}%`:""}`).slice(0,6).join(", ")||"none";
  const err=[s.camera.error,p.error].filter(Boolean).join("\n");$("err").textContent=err;$("err").classList.toggle("hide",!err);
  const btn=$("turboBtn");if(btn)btn.classList.toggle("on",!!s.turbo);
  paintHud(s);paintSkillState(s);drawOverlay(s);
}

function applyDriveState(s){
  if(!s.motion)return;
  $("left").textContent=s.motion.left+"%";$("right").textContent=s.motion.right+"%";
  if(s.control)paintHud(s);
}

let turboOn=false;
async function turboToggle(){
  turboOn=!turboOn;
  const btn=$("turboBtn");btn.textContent=turboOn?"30fps":"Turbo";btn.classList.toggle("on",turboOn);
  const r=await post("/turbo",{on:turboOn});turboOn=r.turbo;
}

async function toggleRecord(){
  try{
    const r=await fetch(recording?"/record/stop":"/record/start",{method:"POST"}),j=await r.json();
    recording=!!j.recording;$("record").textContent=recording?"Stop Rec":"Record";$("record").classList.toggle("recording",recording);
  }catch(e){$("err").textContent="Recorder error: "+e;$("err").classList.remove("hide")}
}

async function toggleVision(){
  visionOn=!visionOn;
  const r=await post(visionOn?"/vision/start":"/vision/stop",{});
  visionOn=!!r.enabled;
  const b=$("visionBtn");if(b){b.textContent=visionOn?"Vision On":"Vision Off";b.classList.toggle("on",visionOn)}
}

async function toggleLockPerson(){
  const r=await post(lockOn?"/skill/stop":"/skill/lock-person",{target:"person"});
  lockOn=!lockOn && r.ok!==false;
  const b=$("lockBtn");if(b){b.textContent=lockOn?"Stop Lock":"Lock Person";b.classList.toggle("on",lockOn)}
}

let driveInFlight=false, driveDirty=false, driveAbort=null, lastDriveAt=0;
async function sendDrive(force=false){
  paintKeys();
  if(driveInFlight){
    driveDirty=true;
    if(force && driveAbort)driveAbort.abort();
    else return;
  }
  const wait=Math.max(0,CONTROL_MS-(performance.now()-lastDriveAt));
  if(wait && !force)await new Promise(r=>setTimeout(r,wait));
  driveInFlight=true;driveDirty=false;driveAbort=new AbortController();lastDriveAt=performance.now();
  try{applyDriveState(await post("/drive",drivePayload(),driveAbort.signal))}
  catch(e){if(e.name!=="AbortError"){driveDirty=true}}
  finally{
    driveInFlight=false;driveAbort=null;
    if(driveDirty)sendDrive();
  }
}
async function stopNow(){down.clear();paintKeys();await post("/motion/stop",{})}
async function settings(){
  const data={crop:+$("crop").value,hflip:$("hflip").checked,vflip:$("vflip").checked};
  $("cropOut").textContent=data.crop+"%";applyState(await post("/camera/settings",data));
}

window.addEventListener("keydown",e=>{const k=e.code?.slice(3).toLowerCase();if(valid.includes(k)){e.preventDefault();if(!down.has(k)){down.add(k);sendDrive()}}});
window.addEventListener("keyup",e=>{const k=e.code?.slice(3).toLowerCase();if(valid.includes(k)){e.preventDefault();down.delete(k);sendDrive()}});
window.addEventListener("blur",stopNow);
power.addEventListener("input",sendDrive);
for(const id of ["crop","hflip","vflip"])$(id).addEventListener("input",settings);
$("showDetections").addEventListener("input",()=>fetch("/api/state").then(r=>r.json()).then(applyState));
setInterval(()=>{if(down.size)sendDrive()},CONTROL_MS);
setInterval(()=>fetch("/api/state").then(r=>r.json()).then(applyState),350);
fetch("/record/status").then(r=>r.json()).then(j=>{recording=!!j.recording;$("record").textContent=recording?"Stop Rec":"Record";$("record").classList.toggle("recording",recording)}).catch(()=>{});
fetch("/vision/status").then(r=>r.json()).then(j=>{visionOn=!!j.enabled;$("visionBtn").textContent=visionOn?"Vision On":"Vision Off";$("visionBtn").classList.toggle("on",visionOn)}).catch(()=>{});
fetch("/api/state").then(r=>r.json()).then(applyState);
document.querySelector("main").focus();paintKeys();
