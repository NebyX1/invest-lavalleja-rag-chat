import enum

class TicketStatus(str, enum.Enum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    ARCHIVED = "ARCHIVED"

    @property
    def label(self):
        return STATUS_TRANSLATIONS.get(self.value, self.value)

STATUS_TRANSLATIONS = {
    "NEW": "Pendiente",
    "IN_PROGRESS": "En Gestión",
    "RESOLVED": "Resuelto",
    "ARCHIVED": "Archivado"
}

CATEGORY_MAPPING = {
    "camineria_rural": "Caminería Rural",
    "alumbrado": "Alumbrado Público",
    "limpieza": "Gestión de Residuos y Limpieza",
    "seguridad": "Seguridad",
    "transito": "Tránsito y Estacionamiento",
    "otros": "Otros Servicios"
}
