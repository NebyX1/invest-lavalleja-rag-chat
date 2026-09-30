"""Herramientas del agente: consultas estructuradas sobre la guía y un simulador de equilibrio."""
import re
from typing import Annotated, Optional

from langchain_core.tools import tool
from pydantic import Field

from rag import Retriever, tokenize

CODE = Annotated[str, Field(pattern=r"^O(0[1-9]|1[0-6])$", description="Código de ficha, de O01 a O16")]
ZONE = Annotated[str, Field(pattern=r"^Z[1-7]$", description="Código de zona, de Z1 a Z7")]

CARD_FIELDS = ["Cliente y negocio.", "Entrada y prueba.", "Condiciones.", "No avanzar cuando…", "MEDIR:"]
CATALOG_LINE = re.compile(r"^- (O\d\d) ([^|]+?) \| zonas: ([^|]+?) \| nivel (\w) \| (.+)$", re.M)

TOOL_LABELS = {
    "buscar_guia": "búsqueda en la guía",
    "ver_ficha": "ficha de oportunidad",
    "ver_zona": "detalle de zona",
    "filtrar_oportunidades": "filtro de oportunidades",
    "comparar_oportunidades": "comparación de oportunidades",
    "contactos_institucionales": "contactos institucionales",
    "simulador_equilibrio": "simulador de equilibrio",
}


def _join(hits, limit):
    out, n = [], 0
    for h in hits:
        block = f"[{h['section']}]\n{h['text']}"
        if n + len(block) > limit:
            break
        out.append(block)
        n += len(block)
    return "\n\n".join(out)


def _pct(x: float) -> float:
    return x / 100 if x > 1 else x


def build_tools(rt: Retriever, overview: str):
    catalog = [m.groups() for m in CATALOG_LINE.finditer(overview)]

    def card_text(code):
        return "\n".join(rt.chunks[i]["text"] for i in rt.cards.get(code, []))

    @tool
    def buscar_guia(consulta: str) -> str:
        """Busca en la Guía de Inversiones 2026 (búsqueda híbrida). Usala para temas puntuales no cubiertos
        por el contexto inicial: permisos, impuestos, incentivos, localización, riesgos, casos, estructura jurídica,
        costos, etc. La consulta debe ser autosuficiente y específica, en español."""
        hits = rt.search_multi(consulta, 6)
        return _join(hits, 6000) or "Sin resultados."

    @tool
    def ver_ficha(codigo: CODE) -> str:
        """Devuelve la ficha completa de una oportunidad (O01 a O16): cliente y negocio, entrada y prueba,
        condiciones, cuándo no avanzar y qué medir. Usala antes de profundizar en una opción."""
        text = card_text(codigo)
        return f"FICHA {codigo}\n{text}"[:5000] if text else "Ficha inexistente."

    @tool
    def ver_zona(zona: ZONE) -> str:
        """Devuelve el detalle de una zona de trabajo (Z1 a Z7): dónde puede estar el negocio, inversor y
        modelo de entrada, prueba comercial, condiciones críticas e indicadores de descarte."""
        ids = rt.zones.get(zona, [])
        return _join([rt.chunks[i] for i in ids], 7000) or "Zona inexistente."

    @tool
    def filtrar_oportunidades(zona: Optional[ZONE] = None, nivel: Optional[str] = None) -> str:
        """Lista las fichas O01–O16 filtradas por zona (Z1–Z7) y/o nivel de prioridad (A, B o C).
        Útil para 'qué oportunidades hay en tal zona' o 'cuáles son de nivel A'."""
        rows = [
            r for r in catalog
            if (not zona or zona in r[2] or "Todas" in r[2]) and (not nivel or r[3] == nivel.upper())
        ]
        return "\n".join(f"{c} {t} | zonas: {z} | nivel {n} | {b}" for c, t, z, n, b in rows) or "Sin coincidencias."

    @tool
    def comparar_oportunidades(codigos: list[CODE]) -> str:
        """Compara de 2 a 4 fichas lado a lado (cliente, forma de entrada, condiciones, alerta de descarte y qué medir)."""
        out = []
        for code in codigos[:4]:
            text = card_text(code)
            if not text:
                continue
            pat = "|".join(re.escape(f) for f in CARD_FIELDS)
            parts = re.split(f"({pat})", text)
            fields = {parts[i]: parts[i + 1].strip()[:450] for i in range(1, len(parts) - 1, 2)}
            title = next((t for c, t, *_ in catalog if c == code), "")
            zn = next((f"zonas {z}, nivel {n}" for c, _, z, n, _ in catalog if c == code), "")
            body = "\n".join(f"  {k} {v}" for k, v in fields.items())
            out.append(f"{code} {title} ({zn})\n{body}")
        return "\n\n".join(out) or "Sin fichas."

    @tool
    def contactos_institucionales(tema: str = "") -> str:
        """Devuelve los canales institucionales publicados en la guía (Intendencia, Uruguay XXI, VUI, UTEC, Centro Pyme,
        ambiente, turismo, RUNAEV…). 'tema' opcional para filtrar (ej: 'turismo', 'ambiental', 'alimentos')."""
        lines, note = [], ""
        for i, c in enumerate(rt.chunks):
            if "CONTACTOS" not in c["section"]:
                continue
            for ln in c["text"].split("\n"):
                if ln.startswith("- "):
                    lines.append(ln)
                elif ln.startswith("No se inventa"):
                    note = ln
        want = set(tokenize(tema))
        sel = [ln for ln in lines if want & set(tokenize(ln))] if want else []
        return "\n".join(sel or lines) + f"\n{note}"

    @tool
    def simulador_equilibrio(
        capacidad_anual: float,
        precio_neto_unitario: float,
        costos_variables_pct: float,
        costos_fijos_anuales: float,
        reserva_anual: float = 0,
        inversion_inicial: Optional[float] = None,
        utilizaciones_pct: Optional[list[float]] = None,
    ) -> str:
        """Simula resultado operativo y punto de equilibrio con los SUPUESTOS DEL USUARIO (nunca inventes las cifras:
        pedilas). capacidad_anual = unidades vendibles por año (ej. habitaciones×365 para alojamiento; toneladas, servicios…).
        precio_neto_unitario = ingreso neto por unidad. costos_variables_pct = % de ingresos (ej. 35).
        costos_fijos_anuales incluye la dirección. utilizaciones_pct = escenarios (por defecto 35, 50 y 65)."""
        var = _pct(costos_variables_pct)
        if min(capacidad_anual, precio_neto_unitario, costos_fijos_anuales) <= 0 or not 0 <= var < 1:
            return "Datos inválidos: capacidad, precio y costos fijos deben ser positivos y costos variables entre 0% y 100%."
        margen = precio_neto_unitario * (1 - var)
        utils = [_pct(u) for u in (utilizaciones_pct or [35, 50, 65])][:5]
        rows = ["| Escenario (utilización) | Ingresos | Resultado operativo | Saldo tras reserva |", "|---|---|---|---|"]
        for u in utils:
            ing = capacidad_anual * u * precio_neto_unitario
            res = ing * (1 - var) - costos_fijos_anuales
            rows.append(f"| {u:.0%} | {ing:,.0f} | {res:,.0f} | {res - reserva_anual:,.0f} |")
        be = costos_fijos_anuales / (capacidad_anual * margen)
        be_r = (costos_fijos_anuales + reserva_anual) / (capacidad_anual * margen)
        txt = "\n".join(rows) + f"\nEquilibrio operativo: {be:.1%} de utilización"
        if reserva_anual:
            txt += f"; incluyendo la reserva: {be_r:.1%}"
        if inversion_inicial and inversion_inicial > 0:
            mid = utils[len(utils) // 2]
            saldo = capacidad_anual * mid * precio_neto_unitario * (1 - var) - costos_fijos_anuales - reserva_anual
            txt += (
                f"\nRecuperación simple en el escenario {mid:.0%}: "
                + (f"{inversion_inicial / saldo:.1f} años" if saldo > 0 else "no se recupera")
                + " (referencial: sin impuestos, deuda ni capital de trabajo; no es una TIR)."
            )
        return txt + "\nEjercicio con supuestos del usuario; no es una valuación ni un dato observado de Lavalleja."

    return [
        buscar_guia, ver_ficha, ver_zona, filtrar_oportunidades,
        comparar_oportunidades, contactos_institucionales, simulador_equilibrio,
    ]
