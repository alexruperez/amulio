from typing import Literal

Locale = Literal["en", "es"]

SUPPORTED_LOCALES: tuple[Locale, ...] = ("en", "es")

MESSAGES: dict[Locale, dict[str, str]] = {
    "en": {
        "page_title": "Install aMulio for Stremio",
        "eyebrow": "YOUR PRIVATE STREMIO ADDON",
        "heading": "Connect Stremio to your aMule library.",
        "intro": (
            "Find eD2K and Kad content, queue downloads with aMule, and play completed "
            "files from storage you control."
        ),
        "readiness": "Instance readiness",
        "amuleapi": "amuleapi",
        "ed2k": "eD2K",
        "kad": "Kad",
        "incoming_storage": "Incoming storage",
        "public_url": "Public URL",
        "checking": "Checking…",
        "private_title": "Private by design",
        "private_body": "Your manifest URL is a private capability.",
        "self_hosted_title": "Self-hosted",
        "self_hosted_body": "aMule and your media stay under your control.",
        "ready_title": "Ready to watch",
        "ready_body": "Completed media plays directly in Stremio.",
        "manifest_label": "Your Stremio manifest URL",
        "install": "Install in Stremio",
        "copy": "Copy manifest URL",
        "copied": "Copied!",
        "copy_failed": "Copy failed — select the URL",
        "tip_label": "Tip:",
        "tip": (
            "if Stremio does not open automatically, copy this URL and paste it into "
            "Stremio's addon search. Keep it private."
        ),
        "footer": "aMulio is a self-hosted Stremio addon powered by aMule.",
        "connected": "Connected",
        "connecting": "Connecting",
        "disconnected": "Disconnected",
        "ready": "Ready",
        "configured": "Configured",
        "unavailable": "Unavailable",
        "unknown": "Unknown",
        "language": "Language",
        "english": "English",
        "spanish": "Spanish",
    },
    "es": {
        "page_title": "Instala aMulio para Stremio",
        "eyebrow": "TU ADDON PRIVADO DE STREMIO",
        "heading": "Conecta Stremio con tu biblioteca de aMule.",
        "intro": (
            "Encuentra contenido eD2K y Kad, encola descargas con aMule y reproduce "
            "archivos completados desde un almacenamiento bajo tu control."
        ),
        "readiness": "Estado de la instancia",
        "amuleapi": "amuleapi",
        "ed2k": "eD2K",
        "kad": "Kad",
        "incoming_storage": "Almacenamiento Incoming",
        "public_url": "URL pública",
        "checking": "Comprobando…",
        "private_title": "Privado por diseño",
        "private_body": "La URL del manifest es una capacidad privada.",
        "self_hosted_title": "Autoalojado",
        "self_hosted_body": "aMule y tus archivos permanecen bajo tu control.",
        "ready_title": "Listo para ver",
        "ready_body": "El contenido completado se reproduce directamente en Stremio.",
        "manifest_label": "Tu URL de manifest de Stremio",
        "install": "Instalar en Stremio",
        "copy": "Copiar URL del manifest",
        "copied": "¡Copiado!",
        "copy_failed": "No se pudo copiar — selecciona la URL",
        "tip_label": "Consejo:",
        "tip": (
            "si Stremio no se abre automáticamente, copia esta URL y pégala en el "
            "buscador de addons de Stremio. Mantenla privada."
        ),
        "footer": "aMulio es un addon autoalojado de Stremio impulsado por aMule.",
        "connected": "Conectado",
        "connecting": "Conectando",
        "disconnected": "Desconectado",
        "ready": "Listo",
        "configured": "Configurada",
        "unavailable": "No disponible",
        "unknown": "Desconocido",
        "language": "Idioma",
        "english": "Inglés",
        "spanish": "Español",
    },
}


def resolve_locale(value: str | None) -> Locale:
    return value if value in SUPPORTED_LOCALES else "en"


def translate(locale: Locale, key: str) -> str:
    return MESSAGES[locale][key]
