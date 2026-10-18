/**
 * localizar_denuncias_map.js
 *
 * Inicializa el mapa Leaflet para el módulo "Localizar Denuncias" del panel
 * administrativo Flask. Carga los marcadores desde un bloque JSON embebido
 * en la plantilla (#ldm-markers-json) y los renderiza con MarkerCluster.
 *
 * Depende de:
 *   - Leaflet (L) cargado localmente desde /public/vendor/leaflet/leaflet.js
 *   - Leaflet.MarkerCluster (L.markerClusterGroup) desde
 *     /public/vendor/leaflet-markercluster/leaflet.markercluster.js
 *
 * No usa ningún CDN. No toca el frontend React.
 */

window.addEventListener("load", function () {
  "use strict";

  const mapElement = document.getElementById("ldm-leaflet-map");
  const jsonElement = document.getElementById("ldm-markers-json");

  if (!mapElement) {
    console.error("Map container #ldm-leaflet-map not found.");
    return;
  }

  if (typeof L === "undefined") {
    console.error("Leaflet was not loaded. Check local static leaflet.js path.");
    return;
  }

  if (typeof L.markerClusterGroup !== "function") {
    console.error(
      "Leaflet MarkerCluster was not loaded. " +
      "Check local static leaflet.markercluster.js path."
    );
    return;
  }

  // ---- Parsear markers desde el JSON embebido en la plantilla ----
  let markers = [];
  try {
    markers = jsonElement ? JSON.parse(jsonElement.textContent || "[]") : [];
  } catch (error) {
    console.error("Invalid markers JSON:", error);
    markers = [];
  }

  // ---- Configurar ruta de imágenes de Leaflet (local) ----
  // Leaflet necesita saber dónde están los iconos por defecto.
  L.Icon.Default.imagePath = "/public/vendor/leaflet/images/";

  // ---- Crear el mapa centrado en Lavalleja, Uruguay ----
  const defaultCenter = [-34.3759, -55.2377];

  const map = L.map("ldm-leaflet-map", {
    center: defaultCenter,
    zoom: 10,
    scrollWheelZoom: true,
    zoomControl: true,
    attributionControl: true,
  });

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  }).addTo(map);

  // ---- Helpers de escape y estilos ----
  function escapeHtml(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function normalizeStatusClass(status) {
    switch (status) {
      case "Pendiente":  return "pendiente";
      case "En Gestión": return "en-gestion";
      case "Resuelto":   return "resuelto";
      case "Archivado":  return "archivado";
      default:           return "default";
    }
  }

  function buildIcon(marker) {
    const statusClass = normalizeStatusClass(marker.status);
    return L.divIcon({
      className: "",
      html: '<div class="ldm-marker ldm-marker-' + statusClass + '"></div>',
      iconSize: [24, 24],
      iconAnchor: [12, 12],
      popupAnchor: [0, -12],
    });
  }

  function buildPopup(marker) {
    const title = escapeHtml(marker.title || marker.tracking_code || "Denuncia");
    const status = escapeHtml(marker.status || "");
    const category = escapeHtml(marker.category || "Sin categoría");
    const description = escapeHtml(marker.description || "");
    const address = escapeHtml(marker.address || marker.locality || "Sin ubicación textual");
    const createdAt = escapeHtml(marker.created_at || "");
    const updatedAt = escapeHtml(marker.updated_at || "");
    const trackingCode = escapeHtml(marker.tracking_code || marker.id || "");
    const detailUrl = marker.detail_url ? escapeHtml(marker.detail_url) : "";
    const mapsUrl = marker.google_maps_url ? escapeHtml(marker.google_maps_url) : "";
    const photoUrl = marker.photo_url ? escapeHtml(marker.photo_url) : "";

    const photoHtml = photoUrl
      ? '<img class="ldm-popup-photo" src="' + photoUrl + '" alt="Foto de la denuncia" loading="lazy">'
      : '<div class="ldm-popup-photo ldm-popup-photo-placeholder">Sin foto</div>';

    const detailButton = detailUrl
      ? '<a href="' + detailUrl + '" class="ldm-popup-button">Ver denuncia</a>'
      : "";

    const mapsButton = mapsUrl
      ? '<a href="' + mapsUrl + '" class="ldm-popup-button ldm-popup-button-secondary" target="_blank" rel="noopener noreferrer">Google Maps</a>'
      : "";

    return '' +
      '<div class="ldm-popup">' +
        photoHtml +
        '<div class="ldm-popup-title">' + title + '</div>' +
        '<div class="ldm-popup-meta"><strong>Estado:</strong> ' + status + '</div>' +
        '<div class="ldm-popup-meta"><strong>Categoría:</strong> ' + category + '</div>' +
        '<div class="ldm-popup-meta"><strong>Código:</strong> ' + trackingCode + '</div>' +
        '<div class="ldm-popup-meta"><strong>Ubicación:</strong> ' + address + '</div>' +
        '<div class="ldm-popup-meta"><strong>Creada:</strong> ' + createdAt + '</div>' +
        '<div class="ldm-popup-meta"><strong>Actualizada:</strong> ' + updatedAt + '</div>' +
        '<div class="ldm-popup-description">' + description + '</div>' +
        '<div class="ldm-popup-actions">' + detailButton + mapsButton + '</div>' +
      '</div>';
  }

  // ---- MarkerCluster ----
  const clusterGroup = L.markerClusterGroup({
    showCoverageOnHover: false,
    maxClusterRadius: 48,
    disableClusteringAtZoom: 16,
    spiderfyOnMaxZoom: true,
    chunkedLoading: true,
  });

  const bounds = [];

  markers.forEach(function (marker) {
    const lat = Number(marker.lat);
    const lng = Number(marker.lng);

    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
      return;
    }
    if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      return;
    }

    const leafletMarker = L.marker([lat, lng], {
      icon: buildIcon(marker),
    });

    leafletMarker.bindPopup(buildPopup(marker), {
      maxWidth: 360,
      className: "ldm-leaflet-popup",
    });

    clusterGroup.addLayer(leafletMarker);
    bounds.push([lat, lng]);
  });

  map.addLayer(clusterGroup);

  if (bounds.length > 0) {
    map.fitBounds(bounds, {
      padding: [40, 40],
      maxZoom: 15,
    });
  } else {
    map.setView(defaultCenter, 10);
  }

  // ---- Leyenda flotante con los 4 estados ----
  const legend = L.control({ position: "bottomright" });
  legend.onAdd = function () {
    const div = L.DomUtil.create("div", "ldm-legend");
    div.style.cssText =
      "position:relative;background:rgba(255,255,255,.96);padding:12px 14px;" +
      "border-radius:16px;box-shadow:0 10px 24px rgba(15,23,42,.18);" +
      "font-family:Inter,system-ui,sans-serif;min-width:160px;";
    const items = [
      { label: "Pendiente",  color: "#f59e0b" },
      { label: "En Gestión", color: "#2563eb" },
      { label: "Resuelto",   color: "#10b981" },
      { label: "Archivado",  color: "#64748b" },
    ];
    let html =
      '<div style="font-size:10px;font-weight:800;letter-spacing:.12em;' +
      'color:#64748b;text-transform:uppercase;margin-bottom:8px;">Estados</div>';
    items.forEach(function (it) {
      html +=
        '<div style="display:flex;align-items:center;gap:8px;font-size:12px;' +
        'color:#0f172a;font-weight:600;margin-bottom:4px;">' +
        '<span style="width:12px;height:12px;border-radius:50%;background:' + it.color + ';' +
        'border:2px solid #fff;box-shadow:0 0 0 1px rgba(15,23,42,.18);"></span>' +
        it.label + "</div>";
    });
    html +=
      '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e2e8f0;' +
      'font-size:11px;color:#475569;font-weight:600;">Mostrando ' +
      markers.length + " marcadores</div>";
    div.innerHTML = html;
    return div;
  };
  legend.addTo(map);

  // ---- Forzar redimensión después del render ----
  setTimeout(function () {
    map.invalidateSize();
  }, 250);
});