const down=new Set(), valid=["w","a","s","d"], CONTROL_MS=20, $=id=>document.getElementById(id), power=$("power"), cv=$("overlay"), ctx=cv.getContext("2d"), recorder="http://127.0.0.1:8765";
let recording=false, lastState={};

function keys(){return valid.filter(k=>down.has(k)).join("")}
function velocityFromKeys(){
  const p=+power.value, y=(down.has("w")?1:0)-(down.has("s")?1:0), x=(down.has("d")?1:0)-(down.has("a")?1:0);
  return {linear:y*p, angular:x*p};
}
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
  const p=s.perception||{}, tracks=p.tracks||[], det=p.detections||[], mem=(s.memory?.inventory||[]).filter(x=>x.box).slice(0,12);
  ctx.lineWidth=3;ctx.font="14px system-ui";ctx.textBaseline="top";
  for(const m of mem)drawBox(m,{stroke:"#f59e0b88",fill:"#2b1807aa",text:"#fde68a",dash:[5,5],width:1},d=>`${d.label} memory ${d.age??"?"}s`);
  for(const d of det)drawBox(d,{stroke:"#60a5fa",fill:"#07152bdd",text:"#dbeafe",dash:[8,5],width:2},d=>`${d.label} pc ${Math.round((d.score||0)*100)}%`);
  for(const t of tracks)drawBox(t,{stroke:"#22d3ee",fill:"#061a1ddd",text:"#cffafe",width:3},d=>`${d.label} track q${Math.round((d.quality||0)*100)} ${d.age?.toFixed?.(1)??"?"}s`);
}

function paintHud(s){
  const c=s.control||{}, ks=new Set(c.keys||"");
  $("mode").textContent=c.mode||"idle";
  for(const k of valid)$("h"+k).classList.toggle("on",ks.has(k)||down.has(k));
}

function applyState(s){
  if(!s.motion)return;
  if(!down.size && s.motion.power!=null){power.value=s.motion.power;$("powerOut").textContent=s.motion.power+"%"}
  $("left").textContent=s.motion.left+"%";$("right").textContent=s.motion.right+"%";
  const c=s.camera.settings,p=s.perception||{};
  $("crop").value=c.crop;$("hflip").checked=!!c.hflip;$("vflip").checked=!!c.vflip;$("cropOut").textContent=c.crop+"%";
  const det=p.detections||[],tracks=p.tracks||[],mem=s.memory?.inventory||[],map=p.map||[],age=p.age==null?"no feed":p.age.toFixed(1)+"s",lat=p.latency?.infer_ms;
  $("vision").textContent=`${p.model||p.backend||"none"} · ${tracks.length} tracks · ${p.fresh?"fresh":"stale"} · ${age}${lat?` · infer ${lat}ms`:""}`;
  $("seen").textContent=(tracks.length?tracks:det).map(d=>`${d.label}${d.quality?` q${Math.round(d.quality*100)}%`:d.score?` ${Math.round(d.score*100)}%`:""}`).slice(0,6).join(", ")||"none";
  $("map").textContent=map.map(x=>`${x.label} ${x.bearing_deg}°/${x.distance_proxy}`).slice(0,6).join(", ")||"empty";
  $("memory").textContent=[...new Set(mem.map(x=>x.label))].slice(0,8).join(", ")||"empty";
  const err=[s.camera.error,p.error].filter(Boolean).join("\n");$("err").textContent=err;$("err").classList.toggle("hide",!err);
  const btn=$("turboBtn");if(btn)btn.classList.toggle("on",!!s.turbo);
  paintHud(s);drawOverlay(s);
}

function applyDriveState(s){
  if(!s.motion)return;
  $("left").textContent=s.motion.left+"%";$("right").textContent=s.motion.right+"%";
  if(s.control)paintHud(s);
}

let turboOn=false;
async function turboToggle(){
  turboOn=!turboOn;
  const btn=$("turboBtn");btn.textContent=turboOn?"⚡30fps":"⚡";btn.classList.toggle("on",turboOn);
  const r=await post("/turbo",{on:turboOn});turboOn=r.turbo;
}

async function toggleRecord(){
  try{
    const r=await fetch(recorder+(recording?"/stop":"/start"),{method:"POST"}),j=await r.json();
    recording=!!j.recording;$("record").textContent=recording?"Stop Rec":"Record";$("record").classList.toggle("recording",recording);
  }catch(e){$("err").textContent="Recorder offline: run bin/record-server";$("err").classList.remove("hide")}
}

let driveInFlight=false, driveDirty=false, driveAbort=null, lastDriveAt=0;
async function sendMotion(force=false){
  paintKeys();
  if(driveInFlight){
    driveDirty=true;
    if(force && driveAbort)driveAbort.abort();
    else return;
  }
  const wait=Math.max(0,CONTROL_MS-(performance.now()-lastDriveAt));
  if(wait && !force)await new Promise(r=>setTimeout(r,wait));
  driveInFlight=true;driveDirty=false;driveAbort=new AbortController();lastDriveAt=performance.now();
  try{applyDriveState(await post("/motion/set_velocity",velocityFromKeys(),driveAbort.signal))}
  catch(e){if(e.name!=="AbortError"){driveDirty=true}}
  finally{
    driveInFlight=false;driveAbort=null;
    if(driveDirty)sendMotion();
  }
}
async function stopNow(){down.clear();paintKeys();await post("/motion/stop",{})}
async function settings(){
  const data={crop:+$("crop").value,hflip:$("hflip").checked,vflip:$("vflip").checked};
  $("cropOut").textContent=data.crop+"%";applyState(await post("/camera/settings",data));
}

window.addEventListener("keydown",e=>{const k=e.code?.slice(3).toLowerCase();if(valid.includes(k)){e.preventDefault();if(!down.has(k)){down.add(k);sendMotion()}}});
window.addEventListener("keyup",e=>{const k=e.code?.slice(3).toLowerCase();if(valid.includes(k)){e.preventDefault();down.delete(k);sendMotion()}});
window.addEventListener("blur",stopNow);
power.addEventListener("input",sendMotion);
for(const id of ["crop","hflip","vflip"])$(id).addEventListener("input",settings);
$("showDetections").addEventListener("input",()=>fetch("/api/state").then(r=>r.json()).then(applyState));
setInterval(()=>{if(down.size)sendMotion()},CONTROL_MS);
setInterval(()=>fetch("/api/state").then(r=>r.json()).then(applyState),350);
fetch(recorder+"/status").then(r=>r.json()).then(j=>{recording=!!j.recording;$("record").textContent=recording?"Stop Rec":"Record";$("record").classList.toggle("recording",recording)}).catch(()=>{});
fetch("/api/state").then(r=>r.json()).then(applyState);
document.querySelector("main").focus();paintKeys();
