/* calendario.js v4 - extensiones del panel v3 (no modifica app.js).
   Se carga DESPUES de app.js (desde el final de app.js o con una etiqueta <script>).
   1) Crea la pestana "Historial": calendario + decisiones por grupo del dia elegido.
      Al elegir un dia cambian a la vez: decisiones por grupo, tarjetas (pasajeros, ocupacion, MAE, acierto)
      y la tabla "Servicios del dia".
   2) Mejora la tarjeta "Decisiones (grupos con 3+ servicios)" del Resumen.
   3) Anade un acceso rapido "Historial" junto a las fechas de viaje.
   Usa lo que ya define app.js: DATOS, HIST_FECHA_IDX, COLORES, colorPct, fmt, fechaLarga, renderPanel, etc. */
(function () {
  "use strict";

  const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
  const DIAS = ["L", "M", "X", "J", "V", "S", "D"];
  let mesVista = null;

  const pad = (n) => String(n).padStart(2, "0");

  function datos() {
    try { return DATOS; } catch (e) { return null; }
  }

  /* indice del dia que app.js esta mostrando (fuente unica de verdad) */
  function indiceActual() {
    try { return HIST_FECHA_IDX; } catch (e) { return null; }
  }

  /* ---------- estilos ---------- */
  function estilos() {
    if (document.getElementById("estilosCalendario")) return;
    const s = document.createElement("style");
    s.id = "estilosCalendario";
    s.textContent = `
      .cal-wrap{max-width:360px}
      .cal-cab{display:flex;align-items:center;justify-content:space-between;margin-bottom:.5rem}
      .cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:4px}
      .cal-dow{font-size:.72rem;text-align:center;color:var(--bs-secondary-color)}
      .cal-dia{aspect-ratio:1/1;border:1px solid var(--bs-border-color);border-radius:8px;background:transparent;
        color:var(--bs-body-color);font-size:.8rem;display:flex;flex-direction:column;align-items:center;
        justify-content:center;line-height:1.1;padding:0}
      .cal-dia[disabled]{opacity:.35;cursor:default}
      .cal-dia.con-datos{color:#fff;border-color:transparent;cursor:pointer}
      .cal-dia.con-datos small{font-size:.62rem;opacity:.9}
      .cal-dia.sel{outline:3px solid var(--bs-primary);outline-offset:1px}
      .cal-leyenda{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.5rem;font-size:.72rem;color:var(--bs-secondary-color)}
      .cal-leyenda i{display:inline-block;width:.7rem;height:.7rem;border-radius:3px;margin-right:.25rem;vertical-align:-1px}
      #tbodyHistGrupos.solo-dec .fila-info{display:none}
      #panelHistorialCal summary{list-style:none}
      #panelHistorialCal summary::-webkit-details-marker{display:none}
      .dec-badges{display:flex;flex-wrap:nowrap;gap:.3rem;font-size:.85rem;font-weight:700;line-height:1.2}
      .dec-badges span{padding:.1rem .45rem;border-radius:999px;color:#fff;white-space:nowrap}
      .dec-leyenda{font-size:.72rem;line-height:1.25;margin-top:.15rem;opacity:.85}
      .kpi-card.dec-click{cursor:pointer}
    `;
    document.head.appendChild(s);
  }

  /* ---------- pestana Historial ---------- */
  const HTML_PANEL = `
    <div class="row g-3">
      <div class="col-lg-4">
        <div class="card border-0 shadow-sm h-100"><div class="card-body">
          <h6 class="mb-1"><i class="bi bi-calendar3 me-2"></i>Predicciones anteriores</h6>
          <div class="small text-secondary mb-3">Elige un d&iacute;a: cambian las decisiones, las tarjetas y los servicios.</div>
          <div id="calHist" class="cal-wrap"></div>
          <select id="selFechaHist" class="d-none" aria-hidden="true" tabindex="-1"></select>
        </div></div>
      </div>
      <div class="col-lg-8">
        <div class="card border-0 shadow-sm h-100" id="cardDecisionesHist"><div class="card-body">
          <h6 class="mb-1" id="tituloDecHist">Decisiones por grupo</h6>
          <div class="small text-secondary mb-2" id="subDecHist"></div>
          <div class="form-check form-switch small mb-2">
            <input class="form-check-input" type="checkbox" id="chkInfoHist">
            <label class="form-check-label" for="chkInfoHist">Mostrar tambi&eacute;n grupos informativos (1-2 servicios)</label>
          </div>
          <div class="table-responsive"><table class="table table-sm align-middle mb-0">
            <thead><tr><th>Empresa</th><th>Tipo</th><th class="text-center">Serv.</th><th class="text-end">Prev. %</th>
              <th class="text-end">Real %</th><th class="text-center">&Delta; difuso</th><th class="text-center">&Delta; regla</th>
              <th class="text-center">&Delta; correcto</th><th class="text-center">Estado</th></tr></thead>
            <tbody id="tbodyHistGrupos" class="solo-dec"></tbody></table></div>
          <div id="sinDecHist" class="small text-secondary py-3 text-center" hidden>
            Ning&uacute;n grupo con 3 o m&aacute;s servicios este d&iacute;a. Activa el interruptor para ver los informativos.</div>
          <div class="small text-secondary mt-3">
            &Delta; = buses a a&ntilde;adir (+) o quitar (&minus;) sobre lo programado. <b>Difuso</b>: lo que recomend&oacute; el sistema;
            <b>regla</b>: la regla fija; <b>correcto</b>: lo necesario con la ocupaci&oacute;n real.
            <b>Exceso</b>: recomend&oacute; m&aacute;s buses de los necesarios; <b>defecto</b>: menos.</div>
        </div></div>
      </div>
      <div class="col-12"><div class="row g-3" id="kpisHistorial"></div></div>
      <div class="col-12">
        <details class="card border-0 shadow-sm" id="detServiciosHist" open>
          <summary class="card-body py-3 fw-semibold" style="cursor:pointer">
            <i class="bi bi-chevron-down me-2"></i><span id="tituloServHist">Servicios del d&iacute;a (prevista frente a real)</span></summary>
          <div class="card-body pt-0">
            <div class="table-responsive"><table class="table table-sm align-middle mb-0">
              <thead><tr><th>Salida</th><th>Empresa</th><th>Tipo</th><th class="text-end">Asientos</th>
                <th class="text-end">Ocup. D+3</th><th class="text-end">Prevista</th><th class="text-end">Real</th>
                <th class="text-end">Error</th></tr></thead>
              <tbody id="tbodyHistServicios"></tbody></table></div>
          </div>
        </details>
      </div>
    </div>`;

  function asegurarPestana() {
    if (document.getElementById("selFechaHist")) return true;
    const modelo = document.querySelector('[data-panel="modelo"]');
    if (!modelo) { console.warn('[calendario.js] No encontre la pestana con data-panel="modelo".'); return false; }
    const objetivo = modelo.dataset.bsTarget || modelo.getAttribute("href");
    const paneModelo = objetivo ? document.querySelector(objetivo) : null;
    if (!paneModelo || !paneModelo.parentElement) {
      console.warn("[calendario.js] No encontre el panel de la pestana Modelo (" + objetivo + ").");
      return false;
    }

    const tab = modelo.cloneNode(true);
    tab.removeAttribute("id");
    tab.dataset.panel = "historial";
    tab.dataset.bsTarget = "#panelHistorialCal";
    if (tab.hasAttribute("href")) tab.setAttribute("href", "#panelHistorialCal");
    tab.classList.remove("active");
    tab.setAttribute("aria-selected", "false");
    tab.innerHTML = '<i class="bi bi-calendar3 me-2"></i>Historial';
    modelo.insertAdjacentElement("afterend", tab);

    const pane = paneModelo.cloneNode(false);
    pane.id = "panelHistorialCal";
    pane.classList.remove("show", "active");
    pane.innerHTML = HTML_PANEL;
    paneModelo.parentElement.appendChild(pane);

    tab.addEventListener("shown.bs.tab", function () {
      try { PANEL = "historial"; } catch (e) { /* ignorar */ }
      window.renderPanel("historial");
    });

    const chk = document.getElementById("chkInfoHist");
    if (chk) chk.addEventListener("change", function () {
      const tb = document.getElementById("tbodyHistGrupos");
      if (tb) tb.classList.toggle("solo-dec", !chk.checked);
      marcarFilas();
    });
    return true;
  }

  function mostrarPanel(nombre) {
    const t = document.querySelector('[data-panel="' + nombre + '"]');
    if (!t) return;
    if (window.bootstrap && bootstrap.Tab) bootstrap.Tab.getOrCreateInstance(t).show();
    else t.click();
  }

  /* ---------- calendario ---------- */
  /* fecha -> {idx, dia}, tomando el indice de DATOS.historial tal como esta ahora */
  function mapaFechas() {
    const D = datos();
    const m = new Map();
    if (!D || !D.historial) return m;
    D.historial.forEach(function (d, i) { m.set(d.fecha_viaje, { idx: i, dia: d }); });
    return m;
  }

  function diaSeleccionado() {
    const D = datos();
    const i = indiceActual();
    if (!D || !D.historial || i === null || i === undefined) return null;
    return D.historial[i] || null;
  }

  /* elige una fecha: fija el indice que usa app.js y vuelve a pintar todo el dia */
  function elegirFecha(fecha) {
    const it = mapaFechas().get(fecha);
    if (!it) return false;
    let directo = true;
    try { HIST_FECHA_IDX = it.idx; } catch (e) { directo = false; console.warn("[calendario.js] No pude fijar HIST_FECHA_IDX:", e.message); }
    const sel = document.getElementById("selFechaHist");
    if (sel) {
      const op = Array.from(sel.options).find(function (o) { return o.textContent.trim().slice(0, 10) === fecha; });
      if (op) sel.value = op.value;
      if (!directo && op) sel.dispatchEvent(new Event("change"));
    }
    if (directo && typeof window.renderHistorialDia === "function") window.renderHistorialDia();
    return true;
  }

  function celdaMes(y, mes, mapa, seleccion, colorFn, fmtFn) {
    const primero = new Date(y, mes, 1);
    const offset = (primero.getDay() + 6) % 7;
    const diasMes = new Date(y, mes + 1, 0).getDate();
    let h = DIAS.map(function (d) { return '<div class="cal-dow">' + d + "</div>"; }).join("");
    for (let i = 0; i < offset; i++) h += "<div></div>";
    for (let d = 1; d <= diasMes; d++) {
      const f = y + "-" + pad(mes + 1) + "-" + pad(d);
      const it = mapa.get(f);
      if (!it) { h += '<button type="button" class="cal-dia" disabled>' + d + "</button>"; continue; }
      const real = it.dia.ocupacion_real_pct;
      const pred = it.dia.ocupacion_predicha_pct;
      const ref = (real !== undefined && real !== null) ? real : pred;
      const tip = "Prev. " + fmtFn(pred, 0) + "%" +
        (real !== undefined && real !== null ? " | Real " + fmtFn(real, 0) + "%" : "") +
        (it.dia.mae_dia !== undefined ? " | MAE " + fmtFn(it.dia.mae_dia, 2) : "");
      h += '<button type="button" class="cal-dia con-datos' + (f === seleccion ? " sel" : "") +
        '" data-fecha="' + f + '" title="' + tip + '" style="background:' + colorFn(ref) + '">' +
        d + "<small>" + fmtFn(ref, 0) + "%</small></button>";
    }
    return h;
  }

  function montarCalendario() {
    const cont = document.getElementById("calHist");
    if (!cont) return;
    const mapa = mapaFechas();
    if (!mapa.size) { cont.innerHTML = '<div class="small text-secondary">Sin historial: ejecuta python src/predict_and_recommend.py.</div>'; return; }
    const fechas = Array.from(mapa.keys()).sort();
    const dia = diaSeleccionado();
    const seleccion = dia ? dia.fecha_viaje : fechas[fechas.length - 1];
    if (!mesVista) mesVista = { y: Number(seleccion.slice(0, 4)), m: Number(seleccion.slice(5, 7)) - 1 };

    const minF = fechas[0], maxF = fechas[fechas.length - 1];
    const claveMes = function (y, m) { return y * 12 + m; };
    const kMin = claveMes(Number(minF.slice(0, 4)), Number(minF.slice(5, 7)) - 1);
    const kMax = claveMes(Number(maxF.slice(0, 4)), Number(maxF.slice(5, 7)) - 1);
    const k = claveMes(mesVista.y, mesVista.m);

    cont.innerHTML =
      '<div class="cal-cab">' +
      '<button type="button" class="btn btn-sm btn-outline-secondary" data-nav="-1"' + (k <= kMin ? " disabled" : "") + '><i class="bi bi-chevron-left"></i></button>' +
      '<strong class="text-capitalize">' + MESES[mesVista.m] + " " + mesVista.y + "</strong>" +
      '<button type="button" class="btn btn-sm btn-outline-secondary" data-nav="1"' + (k >= kMax ? " disabled" : "") + '><i class="bi bi-chevron-right"></i></button>' +
      "</div>" +
      '<div class="cal-grid">' + celdaMes(mesVista.y, mesVista.m, mapa, seleccion, colorPct, fmt) + "</div>" +
      '<div class="cal-leyenda">' +
      '<span><i style="background:' + COLORES.reducir + '"></i>&lt; 45 %</span>' +
      '<span><i style="background:' + COLORES.mantener + '"></i>45-70 %</span>' +
      '<span><i style="background:' + COLORES.aumentar + '"></i>70-90 %</span>' +
      '<span><i style="background:' + COLORES.urgente + '"></i>&ge; 90 %</span>' +
      "<span>Cada d&iacute;a muestra su ocupaci&oacute;n real.</span></div>";

    cont.querySelectorAll("[data-nav]").forEach(function (b) {
      b.addEventListener("click", function () {
        const nuevo = k + Number(b.dataset.nav);
        mesVista = { y: Math.floor(nuevo / 12), m: nuevo % 12 };
        montarCalendario();
      });
    });
    cont.querySelectorAll("[data-fecha]").forEach(function (b) {
      b.addEventListener("click", function () {
        elegirFecha(b.dataset.fecha);
        const tarjeta = document.getElementById("cardDecisionesHist");
        if (tarjeta && tarjeta.scrollIntoView) tarjeta.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });
    });
  }

  /* ---------- decisiones y titulos del dia elegido ---------- */
  function marcarFilas() {
    const tb = document.getElementById("tbodyHistGrupos");
    const aviso = document.getElementById("sinDecHist");
    if (!tb) return;
    let visibles = 0;
    const soloDec = tb.classList.contains("solo-dec");
    tb.querySelectorAll("tr").forEach(function (tr) {
      const ult = tr.lastElementChild ? tr.lastElementChild.textContent : "";
      const info = /informativo/i.test(ult);
      tr.classList.toggle("fila-info", info);
      if (!(soloDec && info) && tr.children.length > 3) visibles++;
    });
    if (aviso) aviso.hidden = visibles > 0;
  }

  function actualizarTitulos() {
    const dia = diaSeleccionado();
    const titulo = document.getElementById("tituloDecHist");
    const sub = document.getElementById("subDecHist");
    const tServ = document.getElementById("tituloServHist");
    if (!dia) return;
    const f = fechaLarga(dia.fecha_viaje);
    if (titulo) titulo.textContent = "Decisiones por grupo \u00b7 " + f;
    if (tServ) tServ.textContent = "Servicios del d\u00eda \u00b7 " + f + " (" + (dia.n_servicios || 0) + " servicios, prevista frente a real)";
    const dec = dia.grupos_decisorios || 0;
    if (sub) sub.textContent = dec
      ? "Lo que recomend\u00f3 el sistema a 72 h frente a lo correcto con la ocupaci\u00f3n real: " +
        (dia.aciertos_decisorios || 0) + " de " + dec + " grupos con decisi\u00f3n exacta."
      : "Este d\u00eda no tiene grupos con 3 o m\u00e1s servicios.";
    marcarFilas();
  }

  function refrescarHistorial() {
    montarCalendario();
    actualizarTitulos();
  }

  /* ---------- tarjeta de decisiones del Resumen ---------- */
  function mejorarDecisiones(r) {
    const c = r && r.resumen;
    const cont = document.getElementById("kpis");
    const D = datos();
    if (!c || !cont) return;
    const tarj = cont.querySelectorAll(".kpi-card")[3];
    if (!tarj) return;
    const valor = tarj.querySelector(".kpi-valor");
    const titulo = valor ? valor.nextElementSibling : null;
    if (!valor || !titulo) return;
    const minS = (D && D.parametros && D.parametros.min_servicios) || 3;
    const dec = c.grupos_decisorios || 0;
    if (!dec) {
      valor.innerHTML = '<span class="text-secondary" style="font-size:.95rem">Sin grupos que decidan</span>';
    } else {
      const b = function (txt, n, color) { return '<span style="background:' + color + '">' + txt + " " + n + "</span>"; };
      valor.innerHTML = '<div class="dec-badges">' +
        b("&uarr;", c.aumentar, COLORES.aumentar) +
        b("=", c.mantener, COLORES.mantener) +
        b("&darr;", c.reducir, COLORES.reducir) + "</div>";
    }
    const info = Math.max((c.grupos || 0) - dec, 0);
    titulo.innerHTML = "Decisiones: " + dec + " grupos con " + minS + "+ servicios" +
      (info ? " (" + info + " informativos)" : "") +
      '<div class="dec-leyenda">&uarr; aumentar &middot; = mantener &middot; &darr; reducir</div>';
    tarj.title = "Solo deciden los grupos (empresa y tipo) con " + minS + " o mas servicios; con 1-2 buses una decision de -2 a +2 no es informativa. Clic para ver el detalle.";
    tarj.classList.add("dec-click");
    if (!tarj.__clic) {
      tarj.__clic = true;
      tarj.addEventListener("click", function () { mostrarPanel("fis"); });
    }
  }

  /* ---------- acceso rapido junto a las fechas ---------- */
  function botonHistorial() {
    const cont = document.getElementById("fechas");
    const D = datos();
    if (!cont || !D || !D.historial || !D.historial.length) return;
    if (document.getElementById("btnCalendario")) return;
    cont.insertAdjacentHTML("beforeend",
      '<button type="button" id="btnCalendario" class="btn btn-sm btn-outline-secondary ms-2">' +
      '<i class="bi bi-calendar3 me-1"></i>Historial</button>');
    document.getElementById("btnCalendario").addEventListener("click", function () { mostrarPanel("historial"); });
  }

  /* ---------- enganche con app.js ---------- */
  function envolver(nombre, despues) {
    const original = window[nombre];
    if (typeof original !== "function") { console.warn("[calendario.js] No existe la funcion " + nombre); return; }
    if (original.__envuelta) return;
    const nueva = function () {
      const res = original.apply(this, arguments);
      try { despues.apply(this, arguments); } catch (e) { console.warn("[calendario.js]", nombre, e); }
      return res;
    };
    nueva.__envuelta = true;
    window[nombre] = nueva;
  }

  function iniciar() {
    estilos();
    asegurarPestana();
    envolver("renderResumen", mejorarDecisiones);
    envolver("renderHistorial", refrescarHistorial);
    envolver("renderHistorialDia", refrescarHistorial);
    envolver("pintarFechas", botonHistorial);
    const D = datos();
    console.info("[calendario.js v4] cargado. Datos listos:", !!(D && D.resultados),
      "| historial:", D && D.historial ? D.historial.length : "sin datos aun",
      "| indice actual:", indiceActual());
    if (D && D.resultados && typeof window.pintarFechas === "function") {
      try { window.pintarFechas(); window.renderPanel(PANEL); } catch (e) { console.warn("[calendario.js] repintado:", e); }
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar);
  else iniciar();

  window.__calendarioTest = { celdaMes: celdaMes, mapaFechas: mapaFechas, elegirFecha: elegirFecha, diaSeleccionado: diaSeleccionado };
})();