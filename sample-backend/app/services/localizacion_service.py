"""
Servicio de Localización Geoespacial de Denuncias (Tickets).

Serializa los tickets con coordenadas válidas para que el template Jinja del
admin los renderice con Leaflet JS directo en el navegador (cargado desde
unpkg.com, que ya está permitido por la CSP del proyecto).

Arquitectura:
- get_localizar_filters(request.args): parsea y valida filtros GET.
- query_tickets_for_map(filters): aplica filtros al modelo Ticket.
- compute_summary(tickets, filters): conteos para tarjetas y CSV.
- serialize_markers(tickets): lista de dicts JSON-safe con los datos
  que el JS del admin necesita para dibujar cada marcador.
- get_ticket_photo_url(ticket): URL segura de MinIO (público o presignada).
- export_tickets_csv(filters): genera el CSV analítico respetando filtros.
- get_distinct_areas / get_distinct_categories: opciones para los selects.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

from app.extensions import db
from app.models.ticket import Ticket, TicketStatus


# Coordenadas del centro por defecto: Lavalleja, Uruguay.
DEFAULT_LAT = -34.3759
DEFAULT_LNG = -55.2377
DEFAULT_ZOOM = 10

# Paleta de colores por estado (consumida por el JS del template).
STATUS_COLORS = {
    TicketStatus.NEW.value: "#f59e0b",        # amber-500 / Pendiente
    TicketStatus.IN_PROGRESS.value: "#2563eb", # blue-600 / En Gestión
    TicketStatus.RESOLVED.value: "#10b981",    # emerald-500 / Resuelto
    TicketStatus.ARCHIVED.value: "#64748b",    # slate-500 / Archivado
}

STATUS_LABEL = {
    TicketStatus.NEW.value: "Pendiente",
    TicketStatus.IN_PROGRESS.value: "En Gestión",
    TicketStatus.RESOLVED.value: "Resuelto",
    TicketStatus.ARCHIVED.value: "Archivado",
}

# Estados activos por defecto (Pendiente + En Gestión).
DEFAULT_ACTIVE_STATUSES = [
    TicketStatus.NEW.value,
    TicketStatus.IN_PROGRESS.value,
]

VALID_STATUSES = [s.value for s in TicketStatus]


@dataclass
class LocalizarFilters:
    """Filtros validados para la consulta de denuncias en el mapa."""
    statuses: List[str] = field(default_factory=lambda: list(DEFAULT_ACTIVE_STATUSES))
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    category: Optional[str] = None
    area: Optional[str] = None  # municipality_or_destination
    q: Optional[str] = None
    has_photo: Optional[str] = None  # 'all' | 'with' | 'without'

    def active_status_values(self) -> List[str]:
        return [s for s in self.statuses if s in VALID_STATUSES]


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    """Parsea una fecha ISO desde query string."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _parse_status_list(raw) -> List[str]:
    """
    Parsea una lista de estados desde query string.

    Soporta dos formatos:
    - status=NEW,IN_PROGRESS (un solo valor con comas)
    - status=NEW&status=IN_PROGRESS (valores repetidos)

    Devuelve sólo los estados válidos.
    """
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple)):
        candidates = raw
    else:
        candidates = str(raw).split(",")
    flat: List[str] = []
    for item in candidates:
        if item is None:
            continue
        flat.extend(str(item).split(","))
    return [p.strip() for p in flat if p and p.strip() in VALID_STATUSES]


def get_localizar_filters(args) -> LocalizarFilters:
    """
    Lee y valida los filtros GET para el módulo de localización.

    Si no se envía el parámetro 'status', se usan los estados activos por
    defecto (Pendiente + En Gestión).
    """
    # Soporta tanto 'status=NEW,IN_PROGRESS' como 'status=NEW&status=IN_PROGRESS'.
    raw_statuses = args.getlist("status") if hasattr(args, "getlist") else args.get("status")
    flat_candidates = []
    for item in raw_statuses if isinstance(raw_statuses, (list, tuple)) else [raw_statuses]:
        if item is None or item == "":
            continue
        flat_candidates.extend(str(item).split(","))

    if not flat_candidates:
        statuses = list(DEFAULT_ACTIVE_STATUSES)
    else:
        statuses = _parse_status_list(flat_candidates)
        if not statuses:
            statuses = list(DEFAULT_ACTIVE_STATUSES)

    has_photo_raw = (args.get("has_photo") or "all").lower()
    if has_photo_raw not in {"all", "with", "without"}:
        has_photo_raw = "all"

    return LocalizarFilters(
        statuses=statuses,
        date_from=_parse_date(args.get("date_from")),
        date_to=_parse_date(args.get("date_to")),
        category=(args.get("category") or "").strip() or None,
        area=(args.get("area") or "").strip() or None,
        q=(args.get("q") or "").strip() or None,
        has_photo=has_photo_raw,
    )


def _apply_filters(query, filters: LocalizarFilters):
    """Aplica los filtros validados a la consulta de Ticket."""
    statuses = filters.active_status_values()
    if statuses:
        query = query.filter(Ticket.status.in_([TicketStatus(s) for s in statuses]))

    if filters.date_from:
        query = query.filter(Ticket.created_at >= filters.date_from)

    if filters.date_to:
        # Inclusivo: incluimos todo el día 'date_to' (hasta 23:59:59).
        end_of_day = filters.date_to + timedelta(days=1) - timedelta(seconds=1)
        query = query.filter(Ticket.created_at <= end_of_day)

    if filters.category:
        query = query.filter(Ticket.category == filters.category)

    if filters.area:
        query = query.filter(Ticket.municipality_or_destination == filters.area)

    if filters.q:
        pattern = f"%{filters.q}%"
        query = query.filter(
            db.or_(
                Ticket.tracking_code.ilike(pattern),
                Ticket.description.ilike(pattern),
                Ticket.category.ilike(pattern),
                Ticket.municipality_or_destination.ilike(pattern),
                Ticket.full_name.ilike(pattern),
            )
        )

    return query


def query_tickets_for_map(filters: LocalizarFilters) -> List[Ticket]:
    """
    Devuelve la lista de tickets filtrados para el mapa y los conteos.
    """
    query = Ticket.query
    query = _apply_filters(query, filters)
    query = query.order_by(Ticket.created_at.desc())
    tickets = query.all()

    if filters.has_photo == "with":
        tickets = [t for t in tickets if t.attachments]
    elif filters.has_photo == "without":
        tickets = [t for t in tickets if not t.attachments]

    return tickets


def compute_summary(tickets: Iterable[Ticket], filters: LocalizarFilters) -> dict:
    """
    Calcula los contadores para las tarjetas resumen y el módulo CSV.
    """
    total = 0
    by_status = {s.value: 0 for s in TicketStatus}
    with_photo = 0
    without_photo = 0
    without_coords = 0
    by_category: dict = {}
    by_area: dict = {}

    for t in tickets:
        total += 1
        by_status[t.status.value] = by_status.get(t.status.value, 0) + 1

        if t.attachments:
            with_photo += 1
        else:
            without_photo += 1

        if t.location_lat is None or t.location_lng is None:
            without_coords += 1

        cat_label = t.category or "Sin categoría"
        by_category[cat_label] = by_category.get(cat_label, 0) + 1

        area_label = t.municipality_or_destination or "Sin asignar"
        by_area[area_label] = by_area.get(area_label, 0) + 1

    return {
        "total": total,
        "by_status": by_status,
        "with_photo": with_photo,
        "without_photo": without_photo,
        "without_coords": without_coords,
        "by_category": sorted(by_category.items(), key=lambda x: x[1], reverse=True),
        "by_area": sorted(by_area.items(), key=lambda x: x[1], reverse=True),
    }


def get_ticket_photo_url(ticket: Ticket) -> Optional[str]:
    """
    Devuelve la URL segura de la primera foto adjunta en MinIO.
    Reutiliza el helper existente de minio_service.get_file_url().
    """
    try:
        if not ticket.attachments:
            return None
        first = ticket.attachments[0]
        from app.services.minio_service import minio_service
        return minio_service.get_file_url(first.object_key)
    except Exception:
        return None


def serialize_markers(tickets: Iterable[Ticket]) -> list:
    """
    Serializa los tickets con coordenadas válidas a una lista de dicts
    JSON-safe, que el template inyecta con `tojson` y el JS del admin usa
    para construir los marcadores del mapa Leaflet.

    - Salta tickets sin lat/lng o con coordenadas inválidas.
    - Reutiliza `get_ticket_photo_url` para la foto segura de MinIO.
    - Devuelve los campos en el formato que consume `buildPopup` en el template.
    """
    markers: list = []
    for t in tickets:
        if t.location_lat is None or t.location_lng is None:
            continue
        try:
            lat = float(t.location_lat)
            lng = float(t.location_lng)
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            continue

        status_val = t.status.value
        status_label = STATUS_LABEL.get(status_val, status_val)
        status_color = STATUS_COLORS.get(status_val, "#64748b")

        category_label = _category_label(t.category)
        title = _short(t.description or "Reporte ciudadano", 80)
        description = _short(t.description or "", 240)
        created_at = t.created_at.strftime("%d/%m/%Y %H:%M") if t.created_at else ""
        updated_at = t.updated_at.strftime("%d/%m/%Y %H:%M") if t.updated_at else ""

        detail_url = f"/admin/tickets/{t.id}"
        google_maps_url = f"https://www.google.com/maps?q={lat},{lng}"

        markers.append({
            "id": t.id,
            "tracking_code": t.tracking_code or "",
            "status": status_label,
            "status_color": status_color,
            "category": category_label,
            "title": title,
            "description": description,
            "address": t.municipality_or_destination or "",
            "locality": "",
            "created_at": created_at,
            "updated_at": updated_at,
            "lat": lat,
            "lng": lng,
            "photo_url": get_ticket_photo_url(t) or "",
            "detail_url": detail_url,
            "google_maps_url": google_maps_url,
        })
    return markers


def _category_label(raw: Optional[str]) -> str:
    """Etiqueta legible para la categoría, usando el mapping existente si aplica."""
    if not raw:
        return "Sin categoría"
    try:
        from app.models.enums import CATEGORY_MAPPING
        return CATEGORY_MAPPING.get(raw, raw)
    except Exception:
        return raw


def _short(text: Optional[str], length: int = 140) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= length:
        return text
    return text[: length - 3].rstrip() + "..."


def export_tickets_csv(filters: LocalizarFilters) -> tuple[bytes, str]:
    """
    Genera un CSV analítico respetando los filtros activos.
    Devuelve (bytes, filename) listo para send_file/Response.
    """
    tickets = query_tickets_for_map(filters)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "codigo_seguimiento", "estado", "categoria", "titulo_descripcion",
        "direccion_area", "latitud", "longitud", "fecha_creacion", "fecha_actualizacion",
        "canal", "tiene_foto", "minio_object_key", "dias_abierta", "dias_hasta_resolucion",
    ])

    now = datetime.utcnow()
    for t in tickets:
        lat = "" if t.location_lat is None else f"{t.location_lat:.6f}"
        lng = "" if t.location_lng is None else f"{t.location_lng:.6f}"

        first_attachment_key = t.attachments[0].object_key if t.attachments else ""
        has_photo = "Sí" if t.attachments else "No"

        if t.status in (TicketStatus.RESOLVED, TicketStatus.ARCHIVED) and t.updated_at:
            dias_resolucion = max((t.updated_at - t.created_at).days, 0)
        else:
            dias_resolucion = ""

        dias_abierta = (now - t.created_at).days if t.created_at else ""

        created = t.created_at.strftime("%Y-%m-%d %H:%M:%S") if t.created_at else ""
        updated = t.updated_at.strftime("%Y-%m-%d %H:%M:%S") if t.updated_at else ""

        writer.writerow([
            t.id,
            t.tracking_code,
            STATUS_LABEL.get(t.status.value, t.status.value),
            _category_label(t.category),
            (t.description or "").replace("\n", " ").strip(),
            t.municipality_or_destination or "",
            lat,
            lng,
            created,
            updated,
            "Web",
            has_photo,
            first_attachment_key,
            dias_abierta,
            dias_resolucion,
        ])

    filename = f"denuncias_localizar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return output.getvalue().encode("utf-8-sig"), filename


def filters_to_query_string(filters: LocalizarFilters) -> str:
    """Reconstruye el querystring a partir de los filtros (para CSV button)."""
    from urllib.parse import urlencode
    params: dict = {}
    if filters.statuses and filters.statuses != list(DEFAULT_ACTIVE_STATUSES):
        params["status"] = ",".join(filters.statuses)
    if filters.date_from:
        params["date_from"] = filters.date_from.strftime("%Y-%m-%d")
    if filters.date_to:
        params["date_to"] = filters.date_to.strftime("%Y-%m-%d")
    if filters.category:
        params["category"] = filters.category
    if filters.area:
        params["area"] = filters.area
    if filters.q:
        params["q"] = filters.q
    if filters.has_photo and filters.has_photo != "all":
        params["has_photo"] = filters.has_photo
    return urlencode(params)


def get_distinct_areas() -> List[str]:
    """Lista de áreas/destinos únicos para el filtro desplegable."""
    rows = (
        db.session.query(Ticket.municipality_or_destination)
        .filter(Ticket.municipality_or_destination.isnot(None))
        .distinct()
        .order_by(Ticket.municipality_or_destination.asc())
        .all()
    )
    return [r[0] for r in rows if r[0]]


def get_distinct_categories() -> List[str]:
    """Lista de categorías únicas (claves crudas) para el filtro desplegable."""
    rows = (
        db.session.query(Ticket.category)
        .filter(Ticket.category.isnot(None))
        .distinct()
        .order_by(Ticket.category.asc())
        .all()
    )
    return [r[0] for r in rows if r[0]]