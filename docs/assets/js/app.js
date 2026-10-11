/* Panel de despacho Lima - Chiclayo
   Lee data/recomendaciones.json (generado por src/predict_and_recommend.py) y pinta el panel. */

const DATA_URL = "data/recomendaciones.json";

const REGLAS = {
  R1_aumentar_urgente: "Demanda alta + feriado muy cercano: aumentar urgente",
  R2_aumentar: "Demanda alta + clima favorable: aumentar",
  R3_aumentar: "Demanda alta + feriado cercano: aumentar",
  R4_mantener: "Demanda media + feriado lejano: mantener",
  R5_mantener: "Demanda media: mantener",
  R6_reducir: "Demanda baja + clima adverso: reducir",
  R7_reducir: "Demanda baja: reducir"
};

let DATOS = null;
let grafico = null;
let seleccionada = null;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const fmt = (n, d = 1) => Number(n).toLocaleString("es-PE", {minimumFractionDigits: d, maximumFractionDigits: d});

/* ---------- utilidades de presentacion ---------- */
function clase(etiqueta) {
  const e = (etiqueta || "").toLowerCase();
  if (e.includes("urgente")) return "urgente";
  if (e.startsWith("aumentar")) return "aumentar";
  if (e.startsWith("reducir")) return "reducir";
  return "mantener";
}
function colorPct(p) {
  return p >= 90 ? "#d93636" : p >= 70 ? "#e8890c" : p >= 45 ? "#2a9d62" : "#2b7fd9";
}
function fechaLarga(f) {
  return new Date(f + "T12:00:00").toLocaleDateString("es-PE", {weekday: "long", day: "numeric", month: "long"});
}
function textoFeriado(d) {
  if (d === 0) return "Es feriado";
  if (d <= -5) return "Sin feriado cercano";
  return "Feriado en " + (-d) + (d === -1 ? " día" : " días");
}
function textoClima(i) {
  return Number(i) === 50 ? "Clima: sin dato (neutro)" : "Índice de clima: " + fmt(i, 0);
}
function barra(pct, color, alto) {
  return '<div class="progress" role="progressbar" aria-valuenow="' + Math.round(pct) + '" aria-valuemin="0" aria-valuemax="100"' +
    (alto ? ' style="height:' + alto + 'px"' : "") + '><div class="progress-bar" style="width:' +
    Math.min(100, Math.max(0, pct)) + '%;background-color:' + color + '"></div></div>';
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
  $("estado").innerHTML = "";
  pintarEncabezado();
  pintarFechas();
  pintarModelo();
  seleccionar(DATOS.resultados[0].fecha_viaje);
}

function mostrarError(html) {
  $("estado").innerHTML = '<div class="alert alert-danger" role="alert">' + html + "</div>";
}

/* ---------- secciones ---------- */
function pintarEncabezado() {
  const m = ["Actualizado: " + DATOS.generado_en, "Modelo: " + DATOS.modelo, "Horizonte: " + DATOS.horizonte];
  if (DATOS.entrenado_en) m.push("Entrenado: " + String(DATOS.entrenado_en).slice(0, 10));
  $("meta").innerHTML = m.map((t) => '<span class="badge-meta">' + esc(t) + "</span>").join("");
}

function pintarFechas() {
  $("dateCards").innerHTML = DATOS.resultados.map((r) =>
    '<div class="col-12 col-md-6 col-lg-4"><div class="card h-100 shadow-sm date-card" data-f="' + esc(r.fecha_viaje) + '">' +
    '<div class="card-body">' +
    '<div class="dia">' + esc(fechaLarga(r.fecha_viaje)) + "</div>" +
    '<div class="grande" style="color:' + colorPct(r.ocupacion_predicha_pct) + '">' + fmt(r.ocupacion_predicha_pct) + "%</div>" +
    '<div class="small text-secondary mb-2">ocupación prevista &middot; ' + r.n_servicios + " servicios</div>" +
    '<div class="fw-semibold mb-2">+' + fmt(r.unidades_recomendadas, 1) + " unidades adicionales</div>" +
    '<span class="badge rounded-pill etiqueta ' + clase(r.recomendacion) + '">' + esc(r.recomendacion) + "</span>" +
    '<div class="small text-secondary mt-3"><i class="bi bi-flag me-1"></i>' + esc(textoFeriado(r.dias_a_feriado)) +
    ' &middot; <i class="bi bi-cloud-sun me-1"></i>' + esc(textoClima(r.indice_clima)) + "</div>" +
    "</div></div></div>"
  ).join("");
  document.querySelectorAll(".date-card").forEach((el) =>
    el.addEventListener("click", () => seleccionar(el.dataset.f)));
}

function seleccionar(f) {
  seleccionada = f;
  document.querySelectorAll(".date-card").forEach((el) => el.classList.toggle("active", el.dataset.f === f));
  const r = DATOS.resultados.find((x) => x.fecha_viaje === f);
  if (!r) return;

  $("detalle").hidden = false;
  $("detalleTitulo").textContent = "Detalle: " + fechaLarga(f);

  const sv = r.servicios.slice().sort((a, b) => a.hora_salida.localeCompare(b.hora_salida));
  const llenos = sv.filter((s) => s.ocupacion_predicha_pct >= 90).length;
  const asientos = sv.reduce((a, s) => a + s.asientos_totales, 0);
  const previstos = sv.reduce((a, s) => a + s.ocupacion_predicha, 0);

  const kpis = [
    ["bi-people", fmt(previstos, 0) + " / " + asientos, "Pasajeros previstos / asientos"],
    ["bi-speedometer2", fmt(r.ocupacion_predicha_pct) + "%", "Ocupación media prevista"],
    ["bi-exclamation-triangle", String(llenos), "Servicios casi llenos (90% o más)"],
    ["bi-plus-circle", "+" + fmt(r.unidades_recomendadas, 1), "Unidades adicionales (FIS)"]
  ];
  $("kpis").innerHTML = kpis.map((k) =>
    '<div class="col-6 col-lg-3"><div class="card h-100 shadow-sm kpi"><div class="card-body">' +
    '<i class="bi ' + k[0] + ' text-primary fs-4"></i><div class="valor">' + k[1] + '</div>' +
    '<div class="small text-secondary">' + k[2] + "</div></div></div></div>").join("");

  $("tbody").innerHTML = sv.map((s) =>
    "<tr><td>" + esc(s.hora_salida) + "</td><td>" + esc(s.operador) + "</td><td>" + esc(s.tipo_bus) + "</td>" +
    '<td class="text-end tabla-num">' + s.asientos_totales + '</td><td class="text-end tabla-num">' + s.ocupacion_d3 + "</td>" +
    '<td class="text-end tabla-num">' + fmt(s.ocupacion_predicha, 0) + "</td>" +
    '<td><div class="barra-ocupacion">' + barra(s.ocupacion_predicha_pct, colorPct(s.ocupacion_predicha_pct), 10) +
    '<span class="pct">' + fmt(s.ocupacion_predicha_pct) + "%</span></div></td></tr>").join("");

  $("reglas").innerHTML = Object.entries(r.reglas_activadas || {}).map(([k, v]) =>
    '<div class="regla"><div class="texto">' + esc(REGLAS[k] || k) + "</div>" +
    '<div class="progress" role="progressbar"><div class="progress-bar bg-primary" style="width:' + Math.round(v * 100) + '%"></div></div>' +
    '<div class="valor">' + fmt(v, 2) + "</div></div>").join("");

  pintarGrafico(sv);
}

function pintarGrafico(sv) {
  if (typeof Chart === "undefined") return;
  const texto = getComputedStyle(document.body).color;
  Chart.defaults.color = texto;
  Chart.defaults.borderColor = "rgba(128,128,128,.2)";
  const labels = sv.map((s) => s.hora_salida + " " + s.operador);
  const d3 = sv.map((s) => s.ocupacion_d3);
  const inc = sv.map((s) => Math.max(0, +(s.ocupacion_predicha - s.ocupacion_d3).toFixed(1)));
  const libres = sv.map((s) => Math.max(0, +(s.asientos_totales - s.ocupacion_predicha).toFixed(1)));
  if (grafico) grafico.destroy();
  grafico = new Chart($("chartServicios"), {
    type: "bar",
    data: {labels, datasets: [
      {label: "Ocupados a D+3 (observado)", data: d3, backgroundColor: "#2459d6"},
      {label: "Aumento previsto hasta la salida", data: inc, backgroundColor: "#8fb0f5"},
      {label: "Asientos libres previstos", data: libres, backgroundColor: "rgba(150,160,180,.35)"}
    ]},
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: {
        x: {stacked: true, ticks: {maxRotation: 70, minRotation: 45, font: {size: 10}}},
        y: {stacked: true, title: {display: true, text: "Asientos"}}
      },
      plugins: {legend: {position: "bottom"}}
    }
  });
}

function pintarModelo() {
  const m = DATOS.metricas_modelo;
  if (!m || !m.length) return;
  $("modelo").hidden = false;
  let info = "Modelo en uso: <strong>" + esc(DATOS.modelo) + "</strong>";
  if (DATOS.n_filas_entrenamiento) {
    info += " &middot; entrenado con " + DATOS.n_filas_entrenamiento + " servicios históricos";
    if (DATOS.entrenamiento_desde && DATOS.entrenamiento_hasta) {
      info += " (" + esc(DATOS.entrenamiento_desde) + " a " + esc(DATOS.entrenamiento_hasta) + ")";
    }
  }
  $("modeloInfo").innerHTML = info;
  $("metricas").innerHTML = m
    .filter((x) => !String(x.modelo).startsWith("Persistencia (final"))
    .map((x) => {
      const mejora = x["mejora_vs_pers+incremento_%"];
      const esRef = x.modelo === "Persistencia + incremento mediano";
      return "<tr><td>" + esc(x.modelo) + (esRef ? ' <span class="badge text-bg-secondary">referencia</span>' : "") + "</td>" +
        '<td class="text-end tabla-num">' + fmt(x.MAE, 2) + '</td><td class="text-end tabla-num">' + fmt(x.RMSE, 2) + "</td>" +
        '<td class="text-end tabla-num">' + (esRef || mejora === undefined ? "-" : fmt(mejora, 1) + "%") + "</td></tr>";
    }).join("");
}

/* ---------- tema claro/oscuro ---------- */
function aplicarTema(t) {
  document.documentElement.setAttribute("data-bs-theme", t);
  try { localStorage.setItem("tema", t); } catch (e) { /* sin almacenamiento */ }
  const icono = $("btnTema") && $("btnTema").querySelector("i");
  if (icono) icono.className = "bi " + (t === "dark" ? "bi-sun-fill" : "bi-moon-stars-fill");
  if (DATOS && seleccionada) seleccionar(seleccionada);
}
function iniciarTema() {
  let t = "light";
  try { t = localStorage.getItem("tema") || (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"); } catch (e) { /* ignorar */ }
  aplicarTema(t);
  $("btnTema").addEventListener("click", () =>
    aplicarTema(document.documentElement.getAttribute("data-bs-theme") === "dark" ? "light" : "dark"));
}

iniciarTema();
cargar();