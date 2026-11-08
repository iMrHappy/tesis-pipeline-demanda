/* Panel de despacho Lima - Chiclayo (v3)
   Lee data/recomendaciones.json (generado por src/predict_and_recommend.py v3) y pinta el panel.
   Librerias: Bootstrap 5 (maquetacion y pestañas), ApexCharts (graficos), animate.css (transiciones). */

const DATA_URL = "data/recomendaciones.json";

const COLORES = {reducir: "#2b7fd9", mantener: "#2a9d62", aumentar: "#e8890c", urgente: "#d93636", neutro: "#9aa5b8"};
const REGLAS = {
  R1_baja_lejos_reducir: "Demanda baja y feriado lejos: reducir",
  R2_media_lejos_mantener: "Demanda media y feriado lejos: mantener",
  R3_alta_lejos_aumentar: "Demanda alta y feriado lejos: aumentar",
  R4_baja_feriado_mantener: "Demanda baja y feriado cerca: mantener",
  R5_media_feriado_aumentar: "Demanda media y feriado cerca: aumentar",
  R6_alta_feriado_urgente: "Demanda alta y feriado cerca: urgente"
};
const TRAMOS_DELTA = [["reducir", 37.5], ["mantener", 25], ["aumentar", 25], ["urgente", 12.5]]; // escala -2..+2 en %
const NOTAS_VISTA = {
  servicio: "Cada barra es un servicio: ocupados a 72 h (azul oscuro), aumento previsto hasta la salida (azul claro) y asientos libres previstos (gris).",
  operador: "Ocupación prevista de cada empresa, ponderada por asientos. Pasa el cursor para ver el detalle.",
  tipo: "Ocupación prevista por tipo de bus, ponderada por asientos. Pasa el cursor para ver el detalle."
};

let DATOS = null;
let FECHA = null;
let PANEL = "resumen";
let VISTA = "servicio";
let ORDEN = "hora";
let BUSCA = "";
let MAXN = 0;
let SOLO_DEC = true;
let GRUPO_SEL = null;
let SORT = {key: "hora_salida", dir: 1};
let HIST_FECHA_IDX = 0;
const charts = {};

/* ---------- utilidades ---------- */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmt = (n, d = 1) => Number(n).toLocaleString("es-PE", {minimumFractionDigits: d, maximumFractionDigits: d});

function clase(etiqueta) {
  const e = (etiqueta || "").toLowerCase();
  if (e.includes("urgente")) return "urgente";
  if (e.startsWith("aumentar")) return "aumentar";
  if (e.startsWith("reducir")) return "reducir";
  if (e.startsWith("sin grupos")) return "neutro";
  return "mantener";
}
function deltaClase(d) { return d >= 2 ? "pos2" : d === 1 ? "pos1" : d === 0 ? "cero" : "neg"; }
function fmtDelta(d) { return d > 0 ? "+" + d : String(d); }
function colorPct(p) {
  return p >= 90 ? COLORES.urgente : p >= 70 ? COLORES.aumentar : p >= 45 ? COLORES.mantener : COLORES.reducir;
}
function fechaLarga(f) {
  return new Date(f + "T12:00:00").toLocaleDateString("es-PE", {weekday: "long", day: "numeric", month: "long"});
}
function fechaCorta(f) {
  return new Date(f + "T12:00:00").toLocaleDateString("es-PE", {weekday: "short", day: "numeric", month: "short"});
}
function textoFeriado(d) {
  if (d === 0) return "Es feriado";
  if (d <= -5) return "Sin feriado cercano";
  return "Feriado en " + (-d) + (d === -1 ? " día" : " días");
}
function tema() { return document.documentElement.getAttribute("data-bs-theme") === "dark" ? "dark" : "light"; }
function resultadoActual() { return DATOS && DATOS.resultados.find((r) => r.fecha_viaje === FECHA); }
function esParcial(r) { return MAXN > 0 && r.n_servicios < 0.6 * MAXN; }
function claveGrupo(g) { return g.operador + "|" + g.tipo_bus; }
function animar(el) {
  if (!el || !el.classList) return;
  el.classList.remove("animate__animated", "animate__fadeIn");
  void el.offsetWidth;
  el.classList.add("animate__animated", "animate__fadeIn");
}
function mezclar(a, b) {
  const o = Object.assign({}, a);
  for (const k in b) {
    const esObj = b[k] && typeof b[k] === "object" && !Array.isArray(b[k]);
    o[k] = esObj && a[k] && typeof a[k] === "object" && !Array.isArray(a[k]) ? mezclar(a[k], b[k]) : b[k];
  }
  return o;
}

/* ---------- graficos (ApexCharts) ---------- */
function baseOpts() {
  const t = tema();
  return {
    chart: {
      fontFamily: "Inter, system-ui, sans-serif", background: "transparent", toolbar: {show: false},
      foreColor: t === "dark" ? "#c9d1e0" : "#4b5565", animations: {enabled: true, speed: 400}
    },
    theme: {mode: t},
    grid: {borderColor: t === "dark" ? "rgba(255,255,255,.09)" : "rgba(0,0,0,.08)"},
    tooltip: {theme: t}
  };
}
function dibujar(clave, selector, opciones) {
  const el = document.querySelector(selector);
  if (charts[clave]) { try { charts[clave].destroy(); } catch (e) { /* ignorar */ } delete charts[clave]; }
  if (!el) return;
  el.innerHTML = "";
  if (typeof ApexCharts === "undefined") {
    el.innerHTML = '<div class="alert alert-secondary small mb-0">No se pudo cargar la librería de gráficos. Revisa tu conexión a internet.</div>';
    return;
  }
  try {
    const c = new ApexCharts(el, mezclar(baseOpts(), opciones));
    c.render();
    charts[clave] = c;
  } catch (e) {
    el.innerHTML = '<div class="alert alert-warning small mb-0">No se pudo dibujar el gráfico: ' + esc(e.message) + "</div>";
  }
}
function opcionesGauge(valorPct, color, textoValor, etiqueta) {
  return {
    chart: {type: "radialBar", height: 290},
    series: [Math.max(0, Math.min(100, valorPct))],
    colors: [color],
    labels: [etiqueta],
    stroke: {lineCap: "round"},
    plotOptions: {radialBar: {
      startAngle: -120, endAngle: 120, hollow: {size: "62%"},
      track: {background: tema() === "dark" ? "rgba(255,255,255,.08)" : "rgba(0,0,0,.07)"},
      dataLabels: {
        name: {offsetY: 24, fontSize: "13px"},
        value: {offsetY: -14, fontSize: "34px", fontWeight: 700, formatter: () => textoValor}
      }
    }}
  };
}

/* ---------- carga ---------- */
async function cargar() {
  try {
    const r = await fetch(DATA_URL + "?t=" + Date.now());
    if (!r.ok) throw new Error("HTTP " + r.status);
    DATOS = await r.json();
  } catch (e) {
    mostrarError("<strong>No se pudieron cargar los datos.</strong> " + esc(e.message) +
      "<br>Si abriste el archivo con doble clic, el navegador bloquea la lectura del JSON. " +
      "Entra a la carpeta <code>docs</code> y ejecuta <code>python -m http.server 8000</code>; luego abre http://localhost:8000.");
    return;
  }
  if (DATOS.error || !DATOS.resultados || !DATOS.resultados.length) {
    mostrarError(esc(DATOS.error || "Sin predicciones disponibles por ahora."));
    return;
  }
  MAXN = Math.max.apply(null, DATOS.resultados.map((r) => r.n_servicios));
  const primera = DATOS.resultados.find((r) => !esParcial(r)) || DATOS.resultados[0];
  FECHA = primera.fecha_viaje;

  $("estado").innerHTML = "";
  $("app").hidden = false;
  pintarEncabezado();
  pintarFechas();
  enlazarEventos();
  renderPanel(PANEL);
}
function mostrarError(html) {
  $("estado").innerHTML = '<div class="alert alert-danger" role="alert">' + html + "</div>";
}

function pintarEncabezado() {
  const m = [
    ["bi-arrow-repeat", "Actualizado: " + DATOS.generado_en],
    ["bi-cpu", "Modelo: " + DATOS.modelo],
    ["bi-clock-history", "Horizonte: " + DATOS.horizonte]
  ];
  if (DATOS.entrenado_en) m.push(["bi-mortarboard", "Entrenado: " + String(DATOS.entrenado_en).slice(0, 10)]);
  $("meta").innerHTML = m.map((x) => '<span class="badge-meta"><i class="bi ' + x[0] + '"></i>' + esc(x[1]) + "</span>").join("");
  $("navActualizado").textContent = "Actualizado " + DATOS.generado_en;
}

function pintarFechas() {
  $("fechas").innerHTML = DATOS.resultados.map((r, i) => {
    const id = "fecha" + i;
    return '<input type="radio" class="btn-check" name="fecha" id="' + id + '" value="' + esc(r.fecha_viaje) + '" autocomplete="off"' +
      (r.fecha_viaje === FECHA ? " checked" : "") + ">" +
      '<label class="btn btn-outline-primary btn-fecha" for="' + id + '"><span class="punto ' + clase(r.recomendacion) + '"></span>' +
      esc(fechaCorta(r.fecha_viaje)) + (esParcial(r) ? ' <span class="badge text-bg-warning ms-1">parcial</span>' : "") + "</label>";
  }).join("");
  document.querySelectorAll('input[name="fecha"]').forEach((el) =>
    el.addEventListener("change", () => seleccionarFecha(el.value)));
}

function seleccionarFecha(f) {
  FECHA = f;
  GRUPO_SEL = null;
  document.querySelectorAll('input[name="fecha"]').forEach((el) => { el.checked = el.value === f; });
  renderPanel(PANEL);
}

function enlazarEventos() {
  document.querySelectorAll("#panelTabs [data-panel]").forEach((el) =>
    el.addEventListener("shown.bs.tab", () => {
      renderPanel(el.dataset.panel);
      animar(document.querySelector(el.dataset.bsTarget));
    }));
  $("vista").addEventListener("change", (e) => { VISTA = e.target.value; renderPanel("servicios"); });
  $("orden").addEventListener("change", (e) => { ORDEN = e.target.value; renderPanel("servicios"); });
  $("buscar").addEventListener("input", (e) => { BUSCA = e.target.value.trim().toLowerCase(); renderPanel("servicios"); });
  $("soloDecisorios").addEventListener("change", (e) => { SOLO_DEC = e.target.checked; renderPanel("fis"); });
  document.querySelectorAll(".tabla-servicios th[data-key]").forEach((th) =>
    th.addEventListener("click", () => {
      SORT = {key: th.dataset.key, dir: SORT.key === th.dataset.key ? -SORT.dir : 1};
      const r = resultadoActual();
      if (r) renderTabla(filtrados(r));
    }));
  $("btnTema").addEventListener("click", () => aplicarTema(tema() === "dark" ? "light" : "dark"));

  const selFechaHist = $("selFechaHist");
  if (selFechaHist) {
    selFechaHist.addEventListener("change", (e) => {
      HIST_FECHA_IDX = Number(e.target.value);
      renderHistorialDia();
    });
  }
}

/* ---------- paneles ---------- */
function renderPanel(nombre) {
  PANEL = nombre;
  const r = resultadoActual();
  if (!r && nombre !== "historial" && nombre !== "acerca") return;
  if (nombre === "resumen") renderResumen(r);
  else if (nombre === "servicios") renderServicios(r);
  else if (nombre === "fis") renderFis(r);
  else if (nombre === "modelo") renderModelo();
  else if (nombre === "historial") renderHistorial();
}

function kpi(icono, color, valor, titulo) {
  return '<div class="col-6 col-xl-3"><div class="card kpi-card border-0 shadow-sm h-100"><div class="card-body d-flex align-items-center gap-3">' +
    '<div class="kpi-icono bg-' + color + '-subtle text-' + color + '-emphasis"><i class="bi ' + icono + '"></i></div>' +
    '<div><div class="kpi-valor">' + valor + '</div><div class="small text-secondary">' + titulo + "</div></div></div></div></div>";
}
function chipEtiqueta(texto) {
  return '<span class="etiqueta ' + clase(texto) + '">' + esc(texto) + "</span>";
}

function renderResumen(r) {
  $("tituloResumen").textContent = "Resumen · " + fechaLarga(r.fecha_viaje) + (esParcial(r) ? " (parcial)" : "");
  const sv = r.servicios;
  const llenos = sv.filter((s) => s.ocupacion_predicha_pct >= 90).length;
  const asientos = sv.reduce((a, s) => a + s.asientos_totales, 0);
  const previstos = sv.reduce((a, s) => a + s.ocupacion_predicha, 0);
  const c = r.resumen;
  const minS = (DATOS.parametros && DATOS.parametros.min_servicios) || 3;
  const decisiones = c
    ? c.aumentar + " ↑ · " + c.mantener + " = · " + c.reducir + " ↓"
    : "-";
  $("kpis").innerHTML =
    kpi("bi-people-fill", "primary", fmt(previstos, 0) + " / " + asientos, "Pasajeros previstos / asientos") +
    kpi("bi-speedometer2", "success", fmt(r.ocupacion_predicha_pct) + "%", "Ocupación media prevista") +
    kpi("bi-exclamation-triangle-fill", "warning", String(llenos), "Servicios casi llenos (90% o más)") +
    kpi("bi-diagram-3-fill", "info", decisiones, "Decisiones (grupos con " + minS + "+ servicios)");

  const pcts = DATOS.resultados.map((x) => x.ocupacion_predicha_pct);
  dibujar("fechas", "#chartFechas", {
    chart: {type: "bar", height: 300},
    series: [{name: "Ocupación prevista", data: pcts}],
    colors: pcts.map(colorPct),
    plotOptions: {bar: {distributed: true, borderRadius: 6, columnWidth: "55%"}},
    dataLabels: {enabled: true, formatter: (v) => fmt(v, 0) + "%", style: {fontSize: "12px"}},
    legend: {show: false},
    xaxis: {categories: DATOS.resultados.map((x) => fechaCorta(x.fecha_viaje) + (esParcial(x) ? " *" : ""))},
    yaxis: {max: 100, labels: {formatter: (v) => fmt(v, 0) + "%"}},
    tooltip: {y: {formatter: (v) => fmt(v, 1) + "%"}}
  });
  dibujar("gauge", "#chartGauge", opcionesGauge(r.ocupacion_predicha_pct, colorPct(r.ocupacion_predicha_pct),
    fmt(r.ocupacion_predicha_pct) + "%", "Ocupación prevista"));
  $("resumenEtiqueta").innerHTML = chipEtiqueta(r.recomendacion || "Sin recomendación") +
    '<div class="small text-secondary mt-2"><i class="bi bi-flag me-1"></i>' + esc(textoFeriado(r.dias_a_feriado)) + "</div>" +
    (DATOS.resultados.some(esParcial) ? '<div class="small text-secondary mt-2">* Fecha parcial: solo incluye servicios que aún no han salido.</div>' : "");
}

function filtrados(r) {
  return r.servicios.filter((s) => !BUSCA ||
    (s.hora_salida + " " + s.operador + " " + s.tipo_bus).toLowerCase().includes(BUSCA));
}
function agrupar(sv, clave) {
  const m = new Map();
  sv.forEach((s) => {
    const g = m.get(s[clave]) || {k: s[clave], n: 0, asientos: 0, prev: 0};
    g.n += 1; g.asientos += s.asientos_totales; g.prev += s.ocupacion_predicha;
    m.set(s[clave], g);
  });
  return Array.from(m.values()).map((g) => Object.assign(g, {pct: g.prev / g.asientos * 100}))
    .sort((a, b) => b.pct - a.pct);
}

function renderServicios(r) {
  $("tituloServicios").textContent = "Servicios · " + fechaLarga(r.fecha_viaje) + (esParcial(r) ? " (parcial)" : "");
  $("notaVista").textContent = NOTAS_VISTA[VISTA];
  const sv = filtrados(r);
  $("contador").textContent = sv.length + " de " + r.servicios.length + " servicios";

  if (!sv.length) {
    if (charts.servicios) { try { charts.servicios.destroy(); } catch (e) { /* ignorar */ } delete charts.servicios; }
    $("chartServicios").innerHTML = '<div class="text-secondary small py-4 text-center">Ningún servicio coincide con la búsqueda.</div>';
    renderTabla(sv);
    return;
  }

  if (VISTA === "servicio") {
    const lista = sv.slice().sort((a, b) => ORDEN === "pct"
      ? b.ocupacion_predicha_pct - a.ocupacion_predicha_pct : a.hora_salida.localeCompare(b.hora_salida));
    const maxAsientos = Math.max.apply(null, lista.map((s) => s.asientos_totales));
    dibujar("servicios", "#chartServicios", {
      chart: {type: "bar", stacked: true, height: Math.max(260, lista.length * 34 + 110)},
      series: [
        {name: "Ocupados a D+3 (observado)", data: lista.map((s) => s.ocupacion_d3)},
        {name: "Aumento previsto hasta la salida", data: lista.map((s) => Math.max(0, +(s.ocupacion_predicha - s.ocupacion_d3).toFixed(1)))},
        {name: "Asientos libres previstos", data: lista.map((s) => Math.max(0, +(s.asientos_totales - s.ocupacion_predicha).toFixed(1)))}
      ],
      colors: ["#2459d6", "#7aa2f7", "#b8c0d4"],
      fill: {opacity: [1, 1, 0.55]},
      plotOptions: {bar: {horizontal: true, barHeight: "64%", borderRadius: 3}},
      dataLabels: {enabled: false},
      legend: {position: "top", horizontalAlign: "left"},
      xaxis: {categories: lista.map((s) => s.hora_salida + " · " + s.operador), max: maxAsientos,
        title: {text: "Asientos"}},
      yaxis: {labels: {maxWidth: 210, style: {fontSize: "12px"}}},
      tooltip: {shared: true, intersect: false, y: {formatter: (v) => fmt(v, 0) + " asientos"}}
    });
  } else {
    const g = agrupar(sv, VISTA === "operador" ? "operador" : "tipo_bus");
    dibujar("servicios", "#chartServicios", {
      chart: {type: "bar", height: Math.max(240, g.length * 42 + 70)},
      series: [{name: "Ocupación prevista", data: g.map((x) => +x.pct.toFixed(1))}],
      colors: g.map((x) => colorPct(x.pct)),
      plotOptions: {bar: {horizontal: true, distributed: true, barHeight: "62%", borderRadius: 4}},
      dataLabels: {enabled: true, formatter: (v) => fmt(v, 0) + "%"},
      legend: {show: false},
      xaxis: {categories: g.map((x) => x.k), max: 100, labels: {formatter: (v) => fmt(v, 0) + "%"}},
      yaxis: {labels: {maxWidth: 210, style: {fontSize: "12px"}}},
      tooltip: {y: {formatter: (v, o) => {
        const x = g[o.dataPointIndex];
        return fmt(v, 1) + "% · " + x.n + (x.n === 1 ? " servicio" : " servicios") + " · " + fmt(x.prev, 0) + " de " + x.asientos + " asientos";
      }}}
    });
  }
  renderTabla(sv);
}

function renderTabla(sv) {
  const lista = sv.slice().sort((a, b) => {
    const x = a[SORT.key], y = b[SORT.key];
    if (typeof x === "number" && typeof y === "number") return (x - y) * SORT.dir;
    return String(x).localeCompare(String(y), "es") * SORT.dir;
  });
  $("tbody").innerHTML = lista.map((s) =>
    "<tr><td>" + esc(s.hora_salida) + "</td><td>" + esc(s.operador) + "</td><td>" + esc(s.tipo_bus) + "</td>" +
    '<td class="text-end tabla-num">' + s.asientos_totales + '</td><td class="text-end tabla-num">' + s.ocupacion_d3 + "</td>" +
    '<td class="text-end tabla-num">' + fmt(s.ocupacion_predicha, 0) + "</td>" +
    '<td><div class="barra-ocupacion"><div class="progress" role="progressbar"><div class="progress-bar" style="width:' +
    Math.min(100, s.ocupacion_predicha_pct) + "%;background-color:" + colorPct(s.ocupacion_predicha_pct) + '"></div></div>' +
    '<span class="pct">' + fmt(s.ocupacion_predicha_pct) + "%</span></div></td></tr>").join("");
}

/* ---------- recomendacion: sistema difuso por empresa y tipo de servicio ---------- */
function seleccionarGrupo(clave) {
  GRUPO_SEL = clave;
  const r = resultadoActual();
  if (r) renderFis(r);
}

function renderFis(r) {
  $("tituloFis").textContent = "Recomendación · " + fechaLarga(r.fecha_viaje) + (esParcial(r) ? " (parcial)" : "");
  const p = DATOS.parametros || {};
  const minS = p.min_servicios || 3;
  const objetivo = Math.round((p.ocupacion_objetivo || 0.85) * 100);
  $("notaFis").innerHTML = "Cada fila es un grupo de <strong>empresa + tipo de servicio</strong>. El sistema difuso recomienda cuántos buses " +
    "<strong>añadir o quitar</strong> sobre lo programado (de −2 a +2). Solo deciden los grupos con " + minS +
    " o más servicios; los demás son informativos. La <em>regla fija</em> es la comparación: calcula los buses necesarios para llegar a una ocupación del " +
    objetivo + " %.";

  if (!r.grupos) {
    $("fisAviso").innerHTML = '<div class="alert alert-warning">Este JSON es de una versión anterior y no trae decisiones por grupo. ' +
      "Ejecuta <code>python src/predict_and_recommend.py</code> para regenerarlo.</div>";
    $("fisContenido").hidden = true;
    return;
  }
  $("fisAviso").innerHTML = "";
  $("fisContenido").hidden = false;

  const lista = r.grupos.filter((g) => !SOLO_DEC || g.decide);
  if (!lista.length) {
    $("tbodyGrupos").innerHTML = '<tr><td colspan="7" class="text-secondary text-center py-4">No hay grupos con ' + minS +
      " o más servicios en esta fecha. Desactiva el filtro para ver todos.</td></tr>";
    $("grupoTitulo").textContent = "Sin grupos que decidan";
    $("grupoDelta").innerHTML = "";
    $("escalaDelta").innerHTML = "";
    $("entradasFis").innerHTML = "";
    $("reglas").innerHTML = "";
    return;
  }
  if (!lista.some((g) => claveGrupo(g) === GRUPO_SEL)) GRUPO_SEL = claveGrupo(lista[0]);

  $("tbodyGrupos").innerHTML = lista.map((g) => {
    const k = claveGrupo(g);
    return '<tr class="' + (g.decide ? "" : "informativo ") + (k === GRUPO_SEL ? "activa" : "") + '" data-g="' + esc(k) + '">' +
      "<td>" + esc(g.operador) + "</td><td>" + esc(g.tipo_bus) + "</td>" +
      '<td class="text-end tabla-num">' + g.n_servicios + "</td>" +
      '<td class="text-end tabla-num">' + fmt(g.ocupacion_predicha_pct) + "%</td>" +
      '<td class="text-center"><span class="delta-badge ' + deltaClase(g.delta_buses) + '">' + fmtDelta(g.delta_buses) + "</span></td>" +
      '<td class="text-center tabla-num">' + fmtDelta(g.delta_regla) + "</td>" +
      "<td>" + (g.decide ? '<span class="badge text-bg-success">Decide</span>' : '<span class="badge text-bg-secondary">Informativo</span>') + "</td></tr>";
  }).join("");
  document.querySelectorAll("#tbodyGrupos tr[data-g]").forEach((tr) =>
    tr.addEventListener("click", () => seleccionarGrupo(tr.dataset.g)));

  renderDetalleGrupo(r, lista.find((g) => claveGrupo(g) === GRUPO_SEL));
}

function renderDetalleGrupo(r, g) {
  $("grupoTitulo").textContent = g.operador + " · " + g.tipo_bus;
  const etiqueta = g.etiqueta || "";
  $("grupoDelta").innerHTML =
    '<div class="delta-grande" style="color:' + COLORES[clase(etiqueta)] + '">' + fmtDelta(g.delta_buses) + "</div>" +
    '<div class="mt-2">' + chipEtiqueta(etiqueta) + "</div>" +
    '<div class="small text-secondary mt-2">buses sobre lo programado · valor continuo ' + fmt(g.delta_continuo, 2) + "</div>" +
    (g.decide ? "" : '<div class="small text-warning mt-1">Informativo: solo ' + g.n_servicios + (g.n_servicios === 1 ? " servicio" : " servicios") + " en el grupo</div>");

  const pos = Math.min(100, Math.max(0, (g.delta_continuo + 2) / 4 * 100));
  $("escalaDelta").innerHTML = TRAMOS_DELTA.map((t) =>
    '<div class="tramo" style="width:' + t[1] + "%;background:" + COLORES[t[0]] + '"></div>').join("") +
    '<div class="marcador" style="left:' + pos + '%"></div>';

  const entradas = [
    ["bi-speedometer2", "Ocupación prevista", fmt(g.ocupacion_predicha_pct) + "%"],
    ["bi-people", "Pasajeros / asientos", fmt(g.pasajeros_previstos, 0) + " / " + g.asientos_totales],
    ["bi-bus-front", "Servicios del grupo", String(g.n_servicios)],
    ["bi-flag", "Feriado", textoFeriado(r.dias_a_feriado)],
    ["bi-rulers", "Regla fija (comparación)", fmtDelta(g.delta_regla) + " buses"],
    ["bi-shield-check", "Soporte de la regla", fmt(g.soporte, 2)]
  ];
  $("entradasFis").innerHTML = entradas.map((e) =>
    '<div class="col-6"><div class="entrada-fis"><div class="small text-secondary"><i class="bi ' + e[0] + ' me-1"></i>' + e[1] +
    '</div><div class="valor">' + esc(e[2]) + "</div></div></div>").join("");

  $("reglas").innerHTML = Object.entries(g.activaciones || {}).map(([k, v]) =>
    '<div class="regla"><div class="texto">' + esc(REGLAS[k] || k) + "</div>" +
    '<div class="progress" role="progressbar"><div class="progress-bar bg-primary" style="width:' + Math.round(v * 100) + '%"></div></div>' +
    '<div class="valor">' + fmt(v, 2) + "</div></div>").join("");
}

/* ---------- modelo y evaluacion (OE1 y OE2) ---------- */
function renderModelo() {
  const m = DATOS.metricas_modelo;
  let info = "Modelo en uso: <strong>" + esc(DATOS.modelo) + "</strong>";
  if (DATOS.n_filas_entrenamiento) {
    info += " &middot; entrenado con " + DATOS.n_filas_entrenamiento + " servicios históricos";
    if (DATOS.entrenamiento_desde && DATOS.entrenamiento_hasta) {
      info += " (" + esc(DATOS.entrenamiento_desde) + " a " + esc(DATOS.entrenamiento_hasta) + ")";
    }
  }
  $("modeloInfo").innerHTML = info;
  if (!m || !m.length) {
    $("chartModelo").innerHTML = '<div class="text-secondary small">Sin métricas disponibles en el JSON.</div>';
    $("metricas").innerHTML = "";
  } else {
    const color = (n) => n.startsWith("Persistencia (final") ? "#9aa5b8" : n.startsWith("Persistencia +") ? COLORES.aumentar
      : n === DATOS.modelo ? COLORES.mantener : "#2459d6";
    dibujar("modelo", "#chartModelo", {
      chart: {type: "bar", height: Math.max(240, m.length * 46 + 60)},
      series: [{name: "MAE", data: m.map((x) => +Number(x.MAE).toFixed(2))}],
      colors: m.map((x) => color(String(x.modelo))),
      plotOptions: {bar: {horizontal: true, distributed: true, barHeight: "60%", borderRadius: 4}},
      dataLabels: {enabled: true, formatter: (v) => fmt(v, 2)},
      legend: {show: false},
      xaxis: {categories: m.map((x) => x.modelo), title: {text: "MAE (asientos)"}},
      yaxis: {labels: {maxWidth: 230, style: {fontSize: "12px"}}},
      tooltip: {y: {formatter: (v) => fmt(v, 2) + " asientos"}}
    });
    $("metricas").innerHTML = m.map((x) => {
      const mejora = x["mejora_vs_pers+incremento_%"];
      const esRef = x.modelo === "Persistencia + incremento mediano";
      const esPura = String(x.modelo).startsWith("Persistencia (final");
      return "<tr><td>" + esc(x.modelo) + (esRef ? ' <span class="badge text-bg-secondary">referencia</span>' : "") +
        (x.modelo === DATOS.modelo ? ' <span class="badge text-bg-success">en uso</span>' : "") + "</td>" +
        '<td class="text-end tabla-num">' + fmt(x.MAE, 2) + '</td><td class="text-end tabla-num">' + fmt(x.RMSE, 2) + "</td>" +
        '<td class="text-end tabla-num">' + (esRef || esPura || mejora === undefined ? "-" : fmt(mejora, 1) + "%") + "</td></tr>";
    }).join("");
  }
  renderEvaluacion();
}

function renderEvaluacion() {
  const ev = DATOS.evaluacion || {};

  const par = ev.prueba_pareada;
  $("bloquePareada").hidden = !(par && par.length);
  if (par && par.length) {
    $("tbodyPareada").innerHTML = par.map((x) =>
      "<tr><td>" + esc(x.A) + " vs " + esc(x.B) + "</td>" +
      '<td class="text-end tabla-num">' + fmt(x["dif_MAE_(B-A)"], 2) + "</td>" +
      '<td class="text-end tabla-num">[' + fmt(x.IC95_inf, 2) + "; " + fmt(x.IC95_sup, 2) + "]</td>" +
      '<td class="text-end tabla-num">' + x.fechas_a_favor_de_A + " de " + x.fechas_total + "</td>" +
      '<td class="text-end tabla-num">' + fmt(x.p_signos, 3) + "</td>" +
      '<td class="small">' + esc(x.lectura) + "</td></tr>").join("");
  }

  const ed = ev.error_decision;
  const principal = (ed || []).filter((x) => String(x.grupos).startsWith(">="));
  $("bloqueDecision").hidden = !principal.length;
  if (principal.length) {
    const p = DATOS.parametros || {};
    $("notaDecision").textContent = "Grupos con " + (p.min_servicios || 3) + " o más servicios (empresa + tipo, por fecha). " +
      "Decisión correcta: la regla fija con los pasajeros observados (ocupación objetivo " + Math.round((p.ocupacion_objetivo || 0.85) * 100) +
      " %). A = referencia + regla; B = XGBoost + regla; C = XGBoost + sistema difuso.";
    $("tbodyDecision").innerHTML = principal.map((x) =>
      "<tr><td>" + esc(x.configuracion) + '</td><td class="text-end tabla-num">' + x.n_grupos + "</td>" +
      '<td class="text-end tabla-num">' + fmt(x["correctas_%"]) + "%</td>" +
      '<td class="text-end tabla-num">' + fmt(x["exceso_%"]) + "%</td>" +
      '<td class="text-end tabla-num">' + fmt(x["defecto_%"]) + "%</td>" +
      '<td class="text-end tabla-num">' + fmt(x.error_medio_abs_buses, 3) + "</td></tr>").join("");
    const cmp = ev.comparaciones_decision || {};
    $("comparacionesDecision").innerHTML = Object.entries(cmp).map(([nombre, c]) =>
      "<div><strong>" + esc(nombre) + ":</strong> mejora en " + c.grupos_mejora + " grupos, empeora en " + c.grupos_empeora +
      ", igual en " + c.grupos_igual + " (prueba de signos p = " + fmt(c.p_signos, 3) + ")</div>").join("");
  }
}

/* ---------- historial ---------- */
function renderHistorial() {
  const hist = DATOS.historial || [];
  if (!hist.length) {
    $("selFechaHist").innerHTML = '<option value="">Sin historial disponible</option>';
    $("tbodyHistGrupos").innerHTML = '<tr><td colspan="9" class="text-center text-secondary py-3">Ejecuta python src/predict_and_recommend.py para generar el historial.</td></tr>';
    $("kpisHistorial").innerHTML = "";
    $("tbodyHistServicios").innerHTML = "";
    return;
  }
  if ($("selFechaHist").options.length === 0 || $("selFechaHist").options.length !== hist.length) {
    $("selFechaHist").innerHTML = hist.map((item, idx) =>
      '<option value="' + idx + '">' + esc(item.fecha_viaje) + ' (' + item.n_servicios + ' serv. &middot; MAE ' + item.mae_dia + ')</option>'
    ).join("");
  }

  const ordenado = [...hist].reverse();
  const categorias = ordenado.map((d) => fechaCorta(d.fecha_viaje));
  const seriePred = ordenado.map((d) => d.ocupacion_predicha_pct);
  const serieReal = ordenado.map((d) => d.ocupacion_real_pct);

  dibujar("histEvol", "#chartHistEvol", {
    chart: {type: "line", height: 280, toolbar: {show: false}},
    series: [
      {name: "Ocup. Predicha (D+3)", data: seriePred},
      {name: "Ocup. Real (D+0)", data: serieReal}
    ],
    colors: ["#3b82f6", "#10b981"],
    stroke: {width: [3, 3], curve: "smooth", dashArray: [4, 0]},
    markers: {size: 4},
    xaxis: {categories: categorias},
    yaxis: {min: 0, max: 100, labels: {formatter: (v) => fmt(v, 0) + "%"}},
    tooltip: {y: {formatter: (v) => fmt(v, 1) + "%"}},
    legend: {position: "top"}
  });

  renderHistorialDia();
}

function renderHistorialDia() {
  const hist = DATOS.historial || [];
  const dia = hist[HIST_FECHA_IDX];
  if (!dia) return;

  const pctAcierto = dia.grupos_decisorios > 0 ? Math.round((dia.aciertos_decisorios / dia.grupos_decisorios) * 100) + "%" : "Sin grupos";

  $("kpisHistorial").innerHTML =
    kpi("bi-people", "primary", fmt(dia.pasajeros_previstos, 0) + " / " + fmt(dia.pasajeros_reales, 0), "Pasajeros (Pred. / Real)") +
    kpi("bi-speedometer2", "success", fmt(dia.ocupacion_predicha_pct) + "% vs " + fmt(dia.ocupacion_real_pct) + "%", "Ocupación media") +
    kpi("bi-bullseye", "warning", fmt(dia.mae_dia, 2), "MAE del día (asientos/bus)") +
    kpi("bi-check2-circle", "info", dia.aciertos_decisorios + "/" + dia.grupos_decisorios + " (" + pctAcierto + ")", "Acierto (n &ge; 3)");

  $("tbodyHistGrupos").innerHTML = dia.grupos.map((g) => {
    let badgeEstado = '<span class="badge bg-secondary-subtle text-secondary">Informativo</span>';
    if (g.decide) {
      if (g.error_decision === 0) badgeEstado = '<span class="badge bg-success-subtle text-success">Exacta (0)</span>';
      else if (g.error_decision > 0) badgeEstado = '<span class="badge bg-warning-subtle text-warning">Exceso (+' + g.error_decision + ')</span>';
      else badgeEstado = '<span class="badge bg-danger-subtle text-danger">Defecto (' + g.error_decision + ')</span>';
    }
    return "<tr>" +
      "<td>" + esc(g.operador) + "</td><td>" + esc(g.tipo_bus) + "</td>" +
      '<td class="text-center tabla-num">' + g.n_servicios + "</td>" +
      '<td class="text-end tabla-num">' + fmt(g.ocupacion_predicha_pct) + "%</td>" +
      '<td class="text-end tabla-num fw-semibold">' + fmt(g.ocupacion_real_pct) + "%</td>" +
      '<td class="text-center fw-bold">' + fmtDelta(g.delta_buses) + "</td>" +
      '<td class="text-center">' + fmtDelta(g.delta_regla) + "</td>" +
      '<td class="text-center text-info">' + fmtDelta(g.delta_correcto) + "</td>" +
      '<td class="text-center">' + badgeEstado + "</td>" +
      "</tr>";
  }).join("");

  $("tbodyHistServicios").innerHTML = dia.servicios.map((s) =>
    "<tr>" +
      '<td class="fw-semibold">' + esc(s.hora_salida) + "</td>" +
      "<td>" + esc(s.operador) + "</td><td>" + esc(s.tipo_bus) + "</td>" +
      '<td class="text-end tabla-num">' + s.asientos_totales + "</td>" +
      '<td class="text-end text-secondary tabla-num">' + s.ocupacion_d3 + "</td>" +
      '<td class="text-end tabla-num">' + fmt(s.ocupacion_predicha, 0) + ' <small class="text-secondary">(' + fmt(s.ocupacion_predicha_pct) + "%)</small></td>" +
      '<td class="text-end fw-semibold tabla-num">' + fmt(s.ocupacion_real, 0) + ' <small class="text-secondary">(' + fmt(s.ocupacion_real_pct) + "%)</small></td>" +
      '<td class="text-end tabla-num ' + (s.error_abs >= 10 ? 'text-warning fw-semibold' : '') + '">' + s.error_abs + "</td>" +
    "</tr>"
  ).join("");
}

/* ---------- tema claro/oscuro ---------- */
function aplicarTema(t) {
  document.documentElement.setAttribute("data-bs-theme", t);
  try { localStorage.setItem("tema", t); } catch (e) { /* sin almacenamiento */ }
  const btn = $("btnTema");
  const icono = btn && btn.querySelector("i");
  if (icono) icono.className = "bi " + (t === "dark" ? "bi-sun-fill" : "bi-moon-stars-fill");
  if (DATOS) renderPanel(PANEL);
}
function temaInicial() {
  try {
    return localStorage.getItem("tema") ||
      (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  } catch (e) { return "light"; }
}

aplicarTema(temaInicial());
cargar();

(function () {
  const s = document.createElement("script");
  s.src = "assets/js/calendario.js?v=4";
  document.body.appendChild(s);
})();
