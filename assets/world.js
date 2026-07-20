/* =========================================================
 * 国別 消費マップ (World Bank: 家計最終消費支出)
 *  - データ: data/world_data.json (scripts/fetch_worldbank.py で生成)
 *  - キーは ISO 3166-1 numeric (ゼロ埋め3桁, world-atlas の id と一致)
 * ========================================================= */

const METRICS = {
  percap: { label:"1人当たり家計消費", unit:"USD/年",  fmt:v=>d3.format(",.0f")(v) },
  total:  { label:"家計消費総額",     unit:"十億USD/年", fmt:v=>d3.format(",.0f")(v) },
  pop:    { label:"人口",             unit:"百万人",   fmt:v=>d3.format(",.1f")(v) }
};
const AI_SCALE = t => d3.interpolateRgbBasis(
  ["#E7EEF5","#B3C9E0","#6E96C4","#33619E","#132F5C"])(t);
const NODATA = "#D9DEE3";

const state = { data:null, year:null, metric:"percap", selected:null, rankAll:false };

function slice(id){ return state.data.countries[id]?.years?.[state.year] ?? null; }
function valueOf(id){ const s = slice(id); return s ? (s[state.metric] ?? null) : null; }

function rankBy(id, metric){
  const m = metric || state.metric;
  const get = i => state.data.countries[i]?.years?.[state.year]?.[m] ?? null;
  const sorted = Object.keys(state.data.countries)
    .filter(i=>get(i)!=null).sort((a,b)=>get(b)-get(a));
  const i = sorted.indexOf(id);
  return i<0 ? null : i+1;
}

/* ---------------- 地図 ---------------- */
const svg = d3.select("#map");
let colorScale = null;

function buildMap(topo){
  const features = topojson.feature(topo, topo.objects.countries).features
    .filter(f => f.id !== "010"); /* 南極を除外 */
  const proj = d3.geoNaturalEarth1().fitExtent([[6,6],[954,474]],
    {type:"FeatureCollection", features});
  svg.append("g").selectAll("path").data(features).join("path")
    .attr("class","country").attr("d", d3.geoPath(proj))
    .on("mousemove", onMove).on("mouseleave", onLeave)
    .on("click",(e,d)=>{ if(state.data.countries[d.id]) selectCountry(d.id); });
}

/* ---------------- 描画更新 ---------------- */
function refresh(){
  const m = METRICS[state.metric];
  const ids = Object.keys(state.data.countries);
  const vals = ids.map(valueOf).filter(v=>v!=null && v>0);
  const ext = d3.extent(vals);
  /* 国別値は桁の開きが大きいため対数スケールで塗る */
  const s = d3.scaleSequentialLog(AI_SCALE).domain(ext);
  colorScale = v => s(v);

  svg.selectAll(".country")
    .attr("fill", d=>{
      const v = valueOf(d.id);
      return v==null ? NODATA : colorScale(v);
    })
    .classed("nodata", d=>!state.data.countries[d.id])
    .classed("selected", d=>d.id===state.selected);

  const stops = d3.range(0,1.01,0.1).map(t=>`${AI_SCALE(t)} ${t*100}%`).join(",");
  document.getElementById("legend-bar").style.background = `linear-gradient(90deg, ${stops})`;
  document.getElementById("legend-min").textContent = vals.length ? m.fmt(ext[0]) : "-";
  document.getElementById("legend-max").textContent = vals.length ? m.fmt(ext[1]) : "-";
  document.getElementById("legend-title").textContent = `${m.label} (${m.unit}, log)`;

  renderRanking();
  renderDetail();
}

function renderRanking(){
  const m = METRICS[state.metric];
  const all = Object.keys(state.data.countries)
    .filter(i=>valueOf(i)!=null)
    .sort((a,b)=>valueOf(b)-valueOf(a));
  const rows = state.rankAll ? all : all.slice(0,10);
  document.getElementById("rank-title").textContent =
    "ランキング" + (state.rankAll ? ` 全${all.length}か国 — ` : " TOP10 — ") + m.label;
  const list = d3.select("#rank-list").classed("full", state.rankAll);
  list.selectAll("*").remove();
  if(!rows.length){
    list.append("p").attr("class","detail-empty")
        .text("この指標のデータがありません。scripts/fetch_worldbank.py で取得してください。");
    return;
  }
  const max = valueOf(rows[0]);
  rows.forEach((id,i)=>{
    const v = valueOf(id);
    const row = list.append("div").attr("class","rank-row")
      .on("click",()=>selectCountry(id))
      .on("mouseenter",()=>highlight(id,true))
      .on("mouseleave",()=>highlight(null,false));
    row.append("span").attr("class","no").text(i+1);
    row.append("span").attr("class","nm").text(state.data.countries[id].name);
    row.append("div").attr("class","bar-track")
      .append("div").attr("class","bar-fill")
      .style("width",(v/max*100)+"%").style("background",colorScale(v));
    row.append("span").attr("class","vl").text(m.fmt(v));
  });
}

function renderDetail(){
  const body = document.getElementById("detail-body");
  const id = state.selected;
  if(id==null){
    body.innerHTML = '<p class="detail-empty">地図上の国をクリックすると詳細を表示します。</p>';
    return;
  }
  const c = state.data.countries[id];
  const s = slice(id) || {};
  let html = `<div class="detail-name">${c.name}
    <small style="font-family:var(--mono);font-size:12px;color:var(--ink-soft)"> ${c.iso3||""} ${state.year}</small></div>`;
  html += ["percap","total","pop"].map(k=>{
    if(s[k]==null) return "";
    const m = METRICS[k];
    const rank = rankBy(id, k);
    return `<div class="stat"><span class="k">${m.label}</span>
      <span class="v">${m.fmt(s[k])}<small>${m.unit}</small>
      ${rank?`<span class="rank">${rank}位</span>`:""}</span></div>`;
  }).join("");

  /* 時系列ミニ表示: 年ごとの1人当たり消費 */
  const years = state.data.meta.years;
  if(years.length>1){
    const series = years.map(y=>[y, c.years?.[y]?.percap]).filter(e=>e[1]!=null);
    if(series.length>1){
      const max = d3.max(series, e=>e[1]);
      html += `<div class="attr-block"><h3>1人当たり家計消費の推移 (USD/年)</h3>
        ${series.map(([y,v])=>`
          <div class="attr-row">
            <span class="al ${y===state.year?'hiA':''}">${y}</span>
            <div class="at"><div class="af" style="width:${v/max*100}%"></div></div>
            <span class="av">${d3.format(",.0f")(v)}</span></div>`).join("")}
      </div>`;
    }
  }
  body.innerHTML = html;
}

function selectCountry(id){
  state.selected = (state.selected===id) ? null : id;
  refresh();
}
function highlight(id,on){
  svg.selectAll(".country").classed("dim", d=> on && d.id!==id);
}

/* ---------------- ツールチップ ---------------- */
const tip = document.getElementById("tooltip");
function onMove(e,d){
  const c = state.data.countries[d.id];
  const m = METRICS[state.metric];
  const v = valueOf(d.id);
  tip.style.display = "block";
  tip.style.left = Math.min(e.clientX+14, innerWidth-250)+"px";
  tip.style.top  = (e.clientY+14)+"px";
  const name = c ? c.name : (d.properties?.name || "—");
  const rank = c ? rankBy(d.id) : null;
  tip.innerHTML = `<div class="t-name">${name} <span style="color:#AEBCD2">${state.year}</span></div>
    <div class="t-val">${v==null?"データなし":m.fmt(v)+" "+m.unit}</div>
    <div class="t-sub">${m.label}${rank?" / "+rank+"位":""}</div>`;
  highlight(d.id,true);
}
function onLeave(){ tip.style.display="none"; highlight(null,false); }

/* ---------------- コントロール ---------------- */
document.getElementById("rank-toggle").addEventListener("click", e=>{
  state.rankAll = !state.rankAll;
  e.target.setAttribute("aria-pressed", String(state.rankAll));
  e.target.textContent = state.rankAll ? "TOP10に戻す" : "全件表示";
  renderRanking();
});

document.querySelectorAll(".toggle button").forEach(btn=>
  btn.addEventListener("click",()=>{
    state.metric = btn.dataset.metric;
    document.querySelectorAll(".toggle button").forEach(b=>
      b.setAttribute("aria-pressed", String(b===btn)));
    refresh();
  }));

function setupYearSlider(){
  const years = state.data.meta.years;
  state.year = years[years.length-1];
  const ctl = document.getElementById("year-ctl");
  const slider = document.getElementById("year-slider");
  const label = document.getElementById("year-label");
  label.textContent = state.year;
  if(years.length<2){ ctl.style.display="none"; return; }
  ctl.style.display = "flex";
  slider.max = years.length-1;
  slider.value = years.length-1;
  slider.addEventListener("input",()=>{
    state.year = years[+slider.value];
    label.textContent = state.year;
    refresh();
  });
}

/* ---------------- 起動 ---------------- */
async function main(){
  try{
    const [topo, raw] = await Promise.all([
      fetch("assets/world.topojson").then(r=>{if(!r.ok)throw 0;return r.json();}),
      fetch("data/world_data.json").then(r=>{if(!r.ok)throw 0;return r.json();})
    ]);
    state.data = raw;
    if(raw.meta?.note)
      document.getElementById("eyebrow").textContent = "SHOHI ATLAS — WORLD / " + raw.meta.note;
    buildMap(topo);
    setupYearSlider();
    refresh();
  }catch(e){
    document.getElementById("load-err").style.display = "block";
  }
}
main();
