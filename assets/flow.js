/* =========================================================
 * 都道府県間フローマップ (人流・物流)
 *  - 未選択時: 純流入のコロプレス + 全国の主要フロー (弧)
 *  - 都道府県を選択: その県を発着する流れを弧で表示
 *  - 弧の色: 流入 = 藍, 流出 = 朱。太さは量に比例
 *  - データ: data/flow_data.json (scripts/fetch_flows.py で生成)
 *    flows[mode][year] = [[from, to, value], ...] (from/to は都道府県コード)
 * ========================================================= */

const PREF_NAMES = {1:"北海道",2:"青森県",3:"岩手県",4:"宮城県",5:"秋田県",6:"山形県",
7:"福島県",8:"茨城県",9:"栃木県",10:"群馬県",11:"埼玉県",12:"千葉県",13:"東京都",
14:"神奈川県",15:"新潟県",16:"富山県",17:"石川県",18:"福井県",19:"山梨県",20:"長野県",
21:"岐阜県",22:"静岡県",23:"愛知県",24:"三重県",25:"滋賀県",26:"京都府",27:"大阪府",
28:"兵庫県",29:"奈良県",30:"和歌山県",31:"鳥取県",32:"島根県",33:"岡山県",34:"広島県",
35:"山口県",36:"徳島県",37:"香川県",38:"愛媛県",39:"高知県",40:"福岡県",41:"佐賀県",
42:"長崎県",43:"熊本県",44:"大分県",45:"宮崎県",46:"鹿児島県",47:"沖縄県"};

const IN_COLOR = "#33619E", OUT_COLOR = "#CE4A3C", NODATA = "#D3DAE0";
const AI_SCALE = t => d3.interpolateRgbBasis(
  ["#E7EEF5","#B3C9E0","#6E96C4","#33619E","#132F5C"])(t);
const DIV_SCALE = t => d3.interpolateRgbBasis(
  ["#A93A2C","#D08A79","#EFECE7","#7FA3CB","#132F5C"])(t);

const state = { data:null, mode:null, dir:"net", year:null, selected:null, rankAll:false };
const centroids = {};   // 都道府県コード → [x, y]
let matrix = {};        // matrix[from][to] = value (現在のmode/year)

const fmtN = d3.format(",");

/* ---------------- データアクセス ---------------- */
function modeMeta(){ return state.data.meta.modes[state.mode]; }
function modeYears(){ return Object.keys(state.data.flows[state.mode]).sort(); }

function buildMatrix(){
  matrix = {};
  const rows = state.data.flows[state.mode][state.year] || [];
  for(const [f,t,v] of rows){
    (matrix[f] = matrix[f] || {})[t] = v;
  }
}
function flowOf(f,t){ return matrix[f]?.[t] ?? 0; }
function inflow(c){ let s=0; for(const f in matrix) s += matrix[f][c]||0; return s; }
function outflow(c){ let s=0; const r=matrix[c]||{}; for(const t in r) s += r[t]; return s; }
function totalOf(c){
  return state.dir==="in" ? inflow(c) : state.dir==="out" ? outflow(c) : inflow(c)-outflow(c);
}

/* ---------------- 地図 ---------------- */
const svg = d3.select("#map");
const W = 760, H = 620;
let gArcs;

function buildMap(topo){
  const features = topojson.feature(topo, topo.objects.japan).features;
  const mainland = features.filter(f=>f.properties.id!==47);
  const okinawa  = features.filter(f=>f.properties.id===47);
  const mainProj = d3.geoMercator().fitExtent([[145,10],[W-10,H-10]],
    {type:"FeatureCollection",features:mainland});
  const okiProj = d3.geoMercator().fitExtent([[26,70],[170,190]],
    {type:"FeatureCollection",features:okinawa});
  const mainPath = d3.geoPath(mainProj), okiPath = d3.geoPath(okiProj);

  svg.append("rect").attr("class","inset-frame")
     .attr("x",16).attr("y",58).attr("width",164).attr("height",144).attr("rx",8);
  svg.append("text").attr("class","inset-label").attr("x",26).attr("y",76).text("OKINAWA");

  const draw = (feats, path) => {
    svg.append("g").selectAll("path").data(feats).join("path")
      .attr("class","pref").attr("d",path)
      .on("mousemove", onMovePref).on("mouseleave", onLeave)
      .on("click",(e,d)=>selectPref(d.properties.id));
    feats.forEach(d=>{ centroids[d.properties.id] = path.centroid(d); });
  };
  draw(mainland, mainPath);
  draw(okinawa, okiPath);
  gArcs = svg.append("g").attr("pointer-events","stroke");
}

function arcPath(a,b){
  const dx=b[0]-a[0], dy=b[1]-a[1], dr=Math.hypot(dx,dy)*1.35;
  return `M${a[0]},${a[1]}A${dr},${dr} 0 0,1 ${b[0]},${b[1]}`;
}

/* ---------------- 弧 (フロー) の選定 ---------------- */
function currentArcs(){
  const sel = state.selected;
  const arcs = [];  // {f, t, v, color}
  if(sel==null){
    /* 全国の主要フロー */
    if(state.dir==="net"){
      const seen = new Set();
      for(const f in matrix) for(const t in matrix[f]){
        const a=+f, b=+t, key=a<b?`${a}-${b}`:`${b}-${a}`;
        if(seen.has(key)) continue; seen.add(key);
        const net = flowOf(a,b)-flowOf(b,a);
        if(net>0) arcs.push({f:a,t:b,v:net,color:IN_COLOR});
        else if(net<0) arcs.push({f:b,t:a,v:-net,color:IN_COLOR});
      }
    }else{
      for(const f in matrix) for(const t in matrix[f])
        arcs.push({f:+f,t:+t,v:matrix[f][t],color:IN_COLOR});
    }
    return arcs.sort((x,y)=>y.v-x.v).slice(0,25);
  }
  /* 選択県を発着するフロー */
  for(const c of Object.keys(PREF_NAMES).map(Number)){
    if(c===sel) continue;
    const vin = flowOf(c,sel), vout = flowOf(sel,c);
    if(state.dir==="in" && vin>0) arcs.push({f:c,t:sel,v:vin,color:IN_COLOR});
    if(state.dir==="out" && vout>0) arcs.push({f:sel,t:c,v:vout,color:OUT_COLOR});
    if(state.dir==="net"){
      const net = vin - vout;
      if(net>0) arcs.push({f:c,t:sel,v:net,color:IN_COLOR});
      else if(net<0) arcs.push({f:sel,t:c,v:-net,color:OUT_COLOR});
    }
  }
  return arcs.sort((x,y)=>y.v-x.v).slice(0,15);
}

/* ---------------- 描画更新 ---------------- */
function refresh(){
  buildMatrix();
  const m = modeMeta();
  const codes = Object.keys(PREF_NAMES).map(Number);
  const vals = codes.map(totalOf);

  /* コロプレス */
  let interp, ext, cscale;
  if(state.dir==="net"){
    const M = d3.max(vals, v=>Math.abs(v)) || 1;
    ext=[-M,M]; interp=DIV_SCALE; cscale = v=>DIV_SCALE((v+M)/(2*M));
  }else{
    ext=d3.extent(vals); interp=AI_SCALE;
    const s=d3.scaleSequential(AI_SCALE).domain(ext); cscale = v=>s(v);
  }
  svg.selectAll(".pref")
    .attr("fill", d=>cscale(totalOf(d.properties.id)))
    .classed("selected", d=>d.properties.id===state.selected);

  const stops = d3.range(0,1.01,0.1).map(t=>`${interp(t)} ${t*100}%`).join(",");
  document.getElementById("legend-bar").style.background=`linear-gradient(90deg, ${stops})`;
  document.getElementById("legend-min").textContent = fmtN(Math.round(ext[0]));
  document.getElementById("legend-max").textContent = fmtN(Math.round(ext[1]));
  const dirLabel = state.dir==="in"?m.in:state.dir==="out"?m.out:`純${m.in}`;
  document.getElementById("legend-title").textContent = `${dirLabel} (${m.unit})`;

  /* 弧 */
  const arcs = currentArcs();
  const wScale = d3.scaleSqrt()
    .domain([0, d3.max(arcs,a=>a.v)||1]).range([0.6, 7]);
  gArcs.selectAll("path").data(arcs, a=>`${a.f}-${a.t}-${a.color}`).join("path")
    .attr("class","flow-line")
    .attr("d", a=>arcPath(centroids[a.f], centroids[a.t]))
    .attr("stroke", a=>a.color)
    .attr("stroke-width", a=>wScale(a.v))
    .attr("fill","none").attr("opacity",0.55)
    .on("mousemove", onMoveArc).on("mouseleave", onLeave);

  renderRanking();
  renderDetail();
}

/* ---------------- ランキング / 詳細 ---------------- */
function renderRanking(){
  const m = modeMeta();
  const sel = state.selected;
  const dirLabel = state.dir==="in"?m.in:state.dir==="out"?m.out:`純${m.in}`;
  let rows;  // [{code, v}]
  if(sel==null){
    rows = Object.keys(PREF_NAMES).map(Number)
      .map(c=>({code:c, v:totalOf(c)}));
    document.getElementById("rank-title").textContent = `都道府県 ${dirLabel}`;
  }else{
    rows = Object.keys(PREF_NAMES).map(Number).filter(c=>c!==sel)
      .map(c=>({code:c, v: state.dir==="in"?flowOf(c,sel)
                        : state.dir==="out"?flowOf(sel,c)
                        : flowOf(c,sel)-flowOf(sel,c)}));
    document.getElementById("rank-title").textContent =
      `${PREF_NAMES[sel]}の${dirLabel} 相手先`;
  }
  rows.sort((a,b)=> state.dir==="net" ? Math.abs(b.v)-Math.abs(a.v) : b.v-a.v);
  const shown = state.rankAll ? rows : rows.slice(0,10);
  const max = d3.max(rows, r=>Math.abs(r.v)) || 1;
  const list = d3.select("#rank-list").classed("full", state.rankAll);
  list.selectAll("*").remove();
  shown.forEach((r,i)=>{
    const row = list.append("div").attr("class","rank-row")
      .on("click",()=>selectPref(r.code))
      .on("mouseenter",()=>highlight(r.code,true))
      .on("mouseleave",()=>highlight(null,false));
    row.append("span").attr("class","no").text(i+1);
    row.append("span").attr("class","nm").text(PREF_NAMES[r.code]);
    row.append("div").attr("class","bar-track")
      .append("div").attr("class","bar-fill")
      .style("width",(Math.abs(r.v)/max*100)+"%")
      .style("background", r.v>=0?IN_COLOR:OUT_COLOR);
    row.append("span").attr("class","vl")
      .text((state.dir==="net"&&r.v>0?"+":"")+fmtN(Math.round(r.v)));
  });
}

function renderDetail(){
  const body = document.getElementById("detail-body");
  const m = modeMeta();
  if(state.selected==null){
    body.innerHTML = `<p class="detail-empty">都道府県をクリックすると、その県を発着する流れを表示します。<br><br>
      地図の弧は全国の主要な${state.dir==="net"?"純フロー":"フロー"} 上位25本です。</p>`;
    return;
  }
  const c = state.selected;
  const vin = inflow(c), vout = outflow(c), net = vin-vout;
  body.innerHTML = `
    <div class="detail-name">${PREF_NAMES[c]}
      <small style="font-family:var(--mono);font-size:12px;color:var(--ink-soft)"> ${state.year}</small></div>
    <div class="stat"><span class="k">${m.in}計</span>
      <span class="v" style="color:${IN_COLOR}">${fmtN(Math.round(vin))}<small>${m.unit}</small></span></div>
    <div class="stat"><span class="k">${m.out}計</span>
      <span class="v" style="color:${OUT_COLOR}">${fmtN(Math.round(vout))}<small>${m.unit}</small></span></div>
    <div class="stat"><span class="k">純${m.in}</span>
      <span class="v">${net>0?"+":""}${fmtN(Math.round(net))}<small>${m.unit}</small></span></div>
    <p class="detail-empty" style="margin-top:10px">
      弧: <span style="color:${IN_COLOR}">■</span> ${m.in} /
      <span style="color:${OUT_COLOR}">■</span> ${m.out} (上位15)。もう一度クリックで解除。</p>`;
}

function selectPref(code){
  state.selected = (state.selected===code) ? null : code;
  refresh();
}
function highlight(code,on){
  svg.selectAll(".pref").classed("dim", d=> on && d.properties.id!==code);
}

/* ---------------- ツールチップ ---------------- */
const tip = document.getElementById("tooltip");
function showTip(e, html){
  tip.style.display="block";
  tip.style.left = Math.min(e.clientX+14, innerWidth-250)+"px";
  tip.style.top  = (e.clientY+14)+"px";
  tip.innerHTML = html;
}
function onMovePref(e,d){
  const c = d.properties.id, m = modeMeta();
  showTip(e, `<div class="t-name">${PREF_NAMES[c]} <span style="color:#AEBCD2">${state.year}</span></div>
    <div class="t-val">${m.in} ${fmtN(Math.round(inflow(c)))} / ${m.out} ${fmtN(Math.round(outflow(c)))}</div>
    <div class="t-sub">純${m.in} ${fmtN(Math.round(inflow(c)-outflow(c)))} ${m.unit}</div>`);
  highlight(c,true);
}
function onMoveArc(e,a){
  const m = modeMeta();
  showTip(e, `<div class="t-name">${PREF_NAMES[a.f]} → ${PREF_NAMES[a.t]}</div>
    <div class="t-val">${fmtN(Math.round(a.v))} ${m.unit}</div>`);
}
function onLeave(){ tip.style.display="none"; highlight(null,false); }

/* ---------------- コントロール ---------------- */
function buildModeToggle(){
  const modes = Object.keys(state.data.meta.modes)
    .filter(k=>state.data.flows[k] && Object.keys(state.data.flows[k]).length);
  const box = document.getElementById("mode-toggle");
  box.innerHTML = modes.map((k,i)=>
    `<button data-mode="${k}" aria-pressed="${i===0}">${
      k==="people"?"人流":k==="goods"?"物流":state.data.meta.modes[k].label}</button>`).join("");
  state.mode = modes[0];
  box.querySelectorAll("button").forEach(b=>
    b.addEventListener("click",()=>{
      state.mode = b.dataset.mode;
      box.querySelectorAll("button").forEach(x=>
        x.setAttribute("aria-pressed", String(x===b)));
      setupYearSlider();
      refresh();
    }));
}

document.querySelectorAll("[data-dir]").forEach(btn=>
  btn.addEventListener("click",()=>{
    state.dir = btn.dataset.dir;
    document.querySelectorAll("[data-dir]").forEach(b=>
      b.setAttribute("aria-pressed", String(b===btn)));
    refresh();
  }));

document.getElementById("rank-toggle").addEventListener("click", e=>{
  state.rankAll = !state.rankAll;
  e.target.setAttribute("aria-pressed", String(state.rankAll));
  e.target.textContent = state.rankAll ? "TOP10に戻す" : "全件表示";
  renderRanking();
});

function setupYearSlider(){
  const years = modeYears();
  state.year = years[years.length-1];
  const ctl = document.getElementById("year-ctl");
  const slider = document.getElementById("year-slider");
  const label = document.getElementById("year-label");
  label.textContent = state.year;
  if(years.length<2){ ctl.style.display="none"; return; }
  ctl.style.display = "flex";
  slider.max = years.length-1;
  slider.value = years.length-1;
  slider.oninput = ()=>{
    state.year = years[+slider.value];
    label.textContent = state.year;
    refresh();
  };
}

/* ---------------- 起動 ---------------- */
async function main(){
  try{
    const [topo, raw] = await Promise.all([
      fetch("assets/japan.topojson").then(r=>{if(!r.ok)throw 0;return r.json();}),
      fetch("data/flow_data.json").then(r=>{if(!r.ok)throw 0;return r.json();})
    ]);
    state.data = raw;
    if(raw.meta?.note)
      document.getElementById("eyebrow").textContent = "SHOHI ATLAS — FLOWS / " + raw.meta.note;
    buildMap(topo);
    buildModeToggle();
    setupYearSlider();
    refresh();
  }catch(e){
    document.getElementById("load-err").style.display = "block";
  }
}
main();
