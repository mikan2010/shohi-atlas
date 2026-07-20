/* =========================================================
 * 都道府県別 消費マップ
 *  - 基本指標 / 属性カテゴリ / 2カテゴリ差分 の3モードで塗り分け
 *  - 年スライダーで時系列切り替え
 *  - データ: data/pref_data.json (scripts/fetch_estat.py で生成)
 * ========================================================= */

const METRICS = {
  percap:        { label:"1人当たり消費支出", unit:"万円/年", fmt:v=>v.toFixed(0) },
  percap_person: { label:"1人当たり消費支出 (推計)", unit:"万円/年", fmt:v=>v.toFixed(1) },
  total:         { label:"消費支出総額",     unit:"兆円/年", fmt:v=>v.toFixed(2) },
  pop:           { label:"人口",             unit:"万人",    fmt:v=>v.toFixed(0) },
  netexp:        { label:"域際収支",         unit:"兆円/年度", fmt:v=>(v>0?"+":"")+v.toFixed(2) }
};
const ATTR_TITLES = { age:"世帯主の年齢階級", income:"年収階級", household:"世帯類型" };
let ATTR_UNIT = "万円/年";

/* 藍の連続スケールと、比較用の朱⇄藍ダイバージングスケール */
const AI_SCALE = t => d3.interpolateRgbBasis(
  ["#E7EEF5","#B3C9E0","#6E96C4","#33619E","#132F5C"])(t);
const DIV_SCALE = t => d3.interpolateRgbBasis(
  ["#A93A2C","#D08A79","#EFECE7","#7FA3CB","#132F5C"])(t);
const NODATA = "#D3DAE0";

const state = {
  data: null,        // {meta:{years}, prefs:{code:{name, years:{y:{...}}}}}
  year: null,
  view: { type:"metric", key:"percap" },
  selected: null,
  rankAll: false
};

/* ---------------- データ読み込み ---------------- */
function normalize(raw){
  if(raw.prefs) return raw;
  /* 旧フラット形式 {code:{name, percap,...}} も受け付ける */
  const prefs = {};
  for(const [c,d] of Object.entries(raw)){
    const {name, ...rest} = d;
    prefs[c] = { name, years:{ latest: rest } };
  }
  return { meta:{years:["latest"]}, prefs };
}

function slice(code){
  return state.data.prefs[code]?.years?.[state.year] ?? null;
}

function valueOf(code){
  const s = slice(code);
  if(!s) return null;
  const v = state.view;
  if(v.type==="metric") return s[v.key] ?? null;
  const a = s.attrs?.[v.attr];
  if(!a) return null;
  if(v.type==="attr") return a[v.cat] ?? null;
  const x = a[v.catA], y = a[v.catB];
  return (x==null||y==null) ? null : x - y;
}

function viewMeta(){
  const v = state.view;
  if(v.type==="metric") return METRICS[v.key];
  const attr = ATTR_TITLES[v.attr]||v.attr;
  if(v.type==="attr")
    return { label:`${attr}「${v.cat}」の1人当たり消費`, unit:ATTR_UNIT, fmt:x=>x.toFixed(0) };
  return { label:`${attr}の差「${v.catA}」−「${v.catB}」`, unit:ATTR_UNIT,
           fmt:x=>(x>0?"+":"")+x.toFixed(0) };
}

function rankBy(code){
  const sorted = Object.keys(state.data.prefs).map(Number)
    .filter(c=>valueOf(c)!=null).sort((a,b)=>valueOf(b)-valueOf(a));
  const i = sorted.indexOf(code);
  return i<0 ? null : i+1;
}

/* ---------------- 地図 ---------------- */
const svg = d3.select("#map");
const W = 760, H = 620;
let colorScale = null;

function buildMap(topo){
  const features = topojson.feature(topo, topo.objects.japan).features;
  const mainland = features.filter(f=>f.properties.id!==47);
  const okinawa  = features.filter(f=>f.properties.id===47);

  const mainProj = d3.geoMercator().fitExtent([[145,10],[W-10,H-10]],
    {type:"FeatureCollection",features:mainland});
  const okiProj = d3.geoMercator().fitExtent([[26,70],[170,190]],
    {type:"FeatureCollection",features:okinawa});

  svg.append("rect").attr("class","inset-frame")
     .attr("x",16).attr("y",58).attr("width",164).attr("height",144).attr("rx",8);
  svg.append("text").attr("class","inset-label").attr("x",26).attr("y",76).text("OKINAWA");
  svg.append("line").attr("class","inset-frame")
     .attr("x1",180).attr("y1",202).attr("x2",250).attr("y2",270);

  const draw = (feats, path) =>
    svg.append("g").selectAll("path").data(feats).join("path")
      .attr("class","pref").attr("d",path)
      .on("mousemove", onMove).on("mouseleave", onLeave)
      .on("click",(e,d)=>selectPref(d.properties.id));
  draw(mainland, d3.geoPath(mainProj));
  draw(okinawa,  d3.geoPath(okiProj));
}

/* ---------------- 描画更新 ---------------- */
function refresh(){
  const m = viewMeta();
  const codes = Object.keys(state.data.prefs).map(Number);
  const vals = codes.map(valueOf).filter(v=>v!=null);

  let interp, ext;
  const hasNeg = vals.length && d3.min(vals)<0 && d3.max(vals)>0;
  if(state.view.type==="diff" || (state.view.type==="metric" && hasNeg)){
    const M = d3.max(vals, v=>Math.abs(v)) || 1;
    ext = [-M, M];
    interp = DIV_SCALE;
    colorScale = v => DIV_SCALE((v+M)/(2*M));
  }else{
    ext = d3.extent(vals);
    interp = AI_SCALE;
    const s = d3.scaleSequential(AI_SCALE).domain(ext);
    colorScale = v => s(v);
  }

  svg.selectAll(".pref")
    .attr("fill", d=>{
      const v = valueOf(d.properties.id);
      return v==null ? NODATA : colorScale(v);
    })
    .classed("selected", d=>d.properties.id===state.selected);

  const stops = d3.range(0,1.01,0.1).map(t=>`${interp(t)} ${t*100}%`).join(",");
  document.getElementById("legend-bar").style.background = `linear-gradient(90deg, ${stops})`;
  document.getElementById("legend-min").textContent = vals.length ? m.fmt(ext[0]) : "-";
  document.getElementById("legend-max").textContent = vals.length ? m.fmt(ext[1]) : "-";
  document.getElementById("legend-title").textContent = `${m.label} (${m.unit})`;

  renderRanking();
  renderDetail();
}

function renderRanking(){
  const m = viewMeta();
  const isDiff = state.view.type==="diff";
  const all = Object.keys(state.data.prefs).map(Number)
    .filter(c=>valueOf(c)!=null)
    .sort((a,b)=> isDiff ? Math.abs(valueOf(b))-Math.abs(valueOf(a)) : valueOf(b)-valueOf(a));
  const rows = state.rankAll ? all : all.slice(0,10);
  document.getElementById("rank-title").textContent =
    (isDiff ? "差が大きい順" : "ランキング")
    + (state.rankAll ? ` 全${all.length}件 — ` : " TOP10 — ") + m.label;
  const list = d3.select("#rank-list").classed("full", state.rankAll);
  list.selectAll("*").remove();
  if(!rows.length){
    list.append("p").attr("class","detail-empty")
        .text("この指標のデータがありません。scripts/fetch_estat.py で取得してください。");
    return;
  }
  const max = isDiff ? Math.abs(valueOf(rows[0])) : valueOf(rows[0]);
  rows.forEach((code,i)=>{
    const v = valueOf(code);
    const w = (isDiff ? Math.abs(v) : v) / max * 100;
    const row = list.append("div").attr("class","rank-row")
      .on("click",()=>selectPref(code))
      .on("mouseenter",()=>highlight(code,true))
      .on("mouseleave",()=>highlight(null,false));
    row.append("span").attr("class","no").text(i+1);
    row.append("span").attr("class","nm").text(state.data.prefs[code].name);
    row.append("div").attr("class","bar-track")
      .append("div").attr("class","bar-fill")
      .style("width",w+"%").style("background",colorScale(v));
    row.append("span").attr("class","vl").text(m.fmt(v));
  });
}

function renderDetail(){
  const body = document.getElementById("detail-body");
  const code = state.selected;
  if(code==null){
    body.innerHTML = '<p class="detail-empty">地図上の都道府県をクリックすると詳細を表示します。</p>';
    return;
  }
  const s = slice(code) || {};
  const v = state.view;
  let html = `<div class="detail-name">${state.data.prefs[code].name}
      <small style="font-family:var(--mono);font-size:12px;color:var(--ink-soft)"> ${state.year}</small></div>`;
  html += ["percap","percap_person","total","pop","netexp"].map(k=>{
    if(s[k]==null) return "";
    const m = METRICS[k];
    const saved = state.view; state.view = {type:"metric", key:k};
    const rank = rankBy(code); state.view = saved;
    return `<div class="stat"><span class="k">${m.label}</span>
      <span class="v">${m.fmt(s[k])}<small>${m.unit}</small>
      ${rank?`<span class="rank">${rank}位</span>`:""}</span></div>`;
  }).join("");

  for(const [attrKey, breakdown] of Object.entries(s.attrs||{})){
    const entries = sortCats(Object.keys(breakdown)).map(k=>[k, breakdown[k]]);
    const max = d3.max(entries, e=>e[1]);
    html += `<div class="attr-block">
      <h3>${ATTR_TITLES[attrKey]||attrKey}別 1人当たり消費 (${ATTR_UNIT})</h3>
      ${entries.map(([label,val])=>{
        const isA = (v.type==="attr" && v.attr===attrKey && v.cat===label)
                 || (v.type==="diff" && v.attr===attrKey && v.catA===label);
        const isB = v.type==="diff" && v.attr===attrKey && v.catB===label;
        return `<div class="attr-row">
          <span class="al ${isA?'hiA':isB?'hiB':''}">${label}</span>
          <div class="at"><div class="af ${isB?'hiB':''}" style="width:${val/max*100}%"></div></div>
          <span class="av">${val.toFixed(0)}</span></div>`;
      }).join("")}
    </div>`;
  }
  body.innerHTML = html;
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
function onMove(e,d){
  const code = d.properties.id;
  const m = viewMeta();
  const v = valueOf(code);
  const rank = rankBy(code);
  tip.style.display = "block";
  tip.style.left = Math.min(e.clientX+14, innerWidth-250)+"px";
  tip.style.top  = (e.clientY+14)+"px";
  tip.innerHTML = `<div class="t-name">${state.data.prefs[code].name} <span style="color:#AEBCD2">${state.year}</span></div>
    <div class="t-val">${v==null?"データなし":m.fmt(v)+" "+m.unit}</div>
    <div class="t-sub">${m.label}${rank?" / 全国 "+rank+"位":""}</div>`;
  highlight(code,true);
}
function onLeave(){ tip.style.display="none"; highlight(null,false); }

/* ---------------- コントロール ---------------- */
const attrDimSel = document.getElementById("attr-dim");
const attrCatSel = document.getElementById("attr-cat");
const attrCat2Sel = document.getElementById("attr-cat2");
const cmpChk = document.getElementById("cmp-chk");
const attrPick = document.getElementById("attr-pick");

/* 「29歳以下→30代→…→70歳以上」のように年齢として自然な順に並べる。
 * 数値を含まないカテゴリは末尾に五十音順で置く */
function catSortKey(name){
  const m = String(name).match(/\d+/);
  if(!m) return 1e9;
  let n = +m[0];
  if(/以下|未満/.test(name)) n -= 0.5;
  return n;
}
function sortCats(cats){
  return cats.slice().sort((x,y)=>
    catSortKey(x)-catSortKey(y) || String(x).localeCompare(String(y),"ja"));
}

function availableAttrs(){
  const dims = {};
  for(const p of Object.values(state.data.prefs))
    for(const s of Object.values(p.years||{}))
      for(const [k,b] of Object.entries(s.attrs||{})){
        dims[k] = dims[k]||new Set();
        Object.keys(b).forEach(c=>dims[k].add(c));
      }
  return dims;
}

function populateAttrSelects(){
  const dims = availableAttrs();
  const keys = Object.keys(dims);
  attrPick.style.display = keys.length ? "flex" : "none";
  if(!keys.length) return;
  const pd=attrDimSel.value, pc=attrCatSel.value, pc2=attrCat2Sel.value;
  attrDimSel.innerHTML = keys.map(k=>`<option value="${k}">${ATTR_TITLES[k]||k}</option>`).join("");
  if(keys.includes(pd)) attrDimSel.value = pd;
  const cats = sortCats([...dims[attrDimSel.value]]);
  const opts = cats.map(c=>`<option value="${c}">${c}</option>`).join("");
  attrCatSel.innerHTML = opts;
  attrCat2Sel.innerHTML = opts;
  if(cats.includes(pc)) attrCatSel.value = pc;
  if(cats.includes(pc2)) attrCat2Sel.value = pc2;
  else if(cats.length>1) attrCat2Sel.value = cats[cats.length-1];
}

function setMetricView(key){
  state.view = {type:"metric", key};
  document.querySelectorAll(".toggle button").forEach(b=>
    b.setAttribute("aria-pressed", String(b.dataset.metric===key)));
  attrPick.classList.remove("active");
  refresh();
}
function setAttrView(){
  document.querySelectorAll(".toggle button").forEach(b=>b.setAttribute("aria-pressed","false"));
  attrPick.classList.add("active");
  const compare = cmpChk.checked;
  document.getElementById("diff-sep").style.display = compare ? "inline" : "none";
  attrCat2Sel.style.display = compare ? "inline-block" : "none";
  state.view = compare
    ? {type:"diff", attr:attrDimSel.value, catA:attrCatSel.value, catB:attrCat2Sel.value}
    : {type:"attr", attr:attrDimSel.value, cat:attrCatSel.value};
  refresh();
}

document.querySelectorAll(".toggle button").forEach(btn=>
  btn.addEventListener("click",()=>setMetricView(btn.dataset.metric)));
attrDimSel.addEventListener("change",()=>{populateAttrSelects();setAttrView();});
attrCatSel.addEventListener("change",setAttrView);
attrCat2Sel.addEventListener("change",setAttrView);
cmpChk.addEventListener("change",setAttrView);

/* ランキング全件表示トグル */
document.getElementById("rank-toggle").addEventListener("click", e=>{
  state.rankAll = !state.rankAll;
  e.target.setAttribute("aria-pressed", String(state.rankAll));
  e.target.textContent = state.rankAll ? "TOP10に戻す" : "全件表示";
  renderRanking();
});

/* 年スライダー */
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
/* データ側 (meta.metrics / meta.attr_unit) からラベル・単位を上書きできる。
 * quickstart_japan.py は「1世帯当たり (万円/月)」等の正しい表記をここ経由で反映する */
function applyMetricOverrides(){
  const mm = state.data.meta?.metrics || {};
  for(const [k,o] of Object.entries(mm)){
    if(!METRICS[k]) continue;
    if(o.label) METRICS[k].label = o.label;
    if(o.unit)  METRICS[k].unit  = o.unit;
    if(o.digits!=null) METRICS[k].fmt = v=>v.toFixed(o.digits);
  }
  if(state.data.meta?.attr_unit) ATTR_UNIT = state.data.meta.attr_unit;
  /* ボタンの表記も上書き: short があればそれを、なければ label から短縮形を作る */
  document.querySelectorAll(".toggle button").forEach(b=>{
    const o = mm[b.dataset.metric];
    if(!o) return;
    if(o.short) b.textContent = o.short;
    else if(o.label){
      const s = o.label.replace(/消費支出.*/, "");
      if(s && s.length <= 8) b.textContent = s;
    }
  });
}

/* データが1件もない指標のボタンは隠す (例: quickstart は percap のみ提供) */
function pruneMetricButtons(){
  document.querySelectorAll(".toggle button").forEach(b=>{
    const k = b.dataset.metric;
    const has = Object.values(state.data.prefs).some(p=>
      Object.values(p.years||{}).some(s=>s[k]!=null));
    b.style.display = has ? "" : "none";
  });
}

async function main(){
  try{
    const [topo, raw] = await Promise.all([
      fetch("assets/japan.topojson").then(r=>{if(!r.ok)throw 0;return r.json();}),
      fetch("data/pref_data.json").then(r=>{if(!r.ok)throw 0;return r.json();})
    ]);
    state.data = normalize(raw);
    applyMetricOverrides();
    pruneMetricButtons();
    if(state.data.meta?.note)
      document.getElementById("eyebrow").textContent =
        "SHOHI ATLAS — JAPAN / " + state.data.meta.note;
    buildMap(topo);
    setupYearSlider();
    populateAttrSelects();
    refresh();
  }catch(e){
    document.getElementById("load-err").style.display = "block";
  }
}
main();
