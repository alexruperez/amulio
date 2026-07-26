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
        "stream_ready": "Ready to play",
        "stream_download": "Download with aMule",
        "stream_downloading": "Downloading in aMule",
        "stream_completed": "Completed local file",
        "stream_sources": "{total} sources ({complete} complete)",
        "stream_active_sources": "{count} active sources",
        "stream_quality_fallback": "video",
        "stream_no_results": "No matching files found",
        "stream_no_results_detail": "Try another title or check aMule network connectivity.",
        "stream_unavailable": "aMule is unavailable",
        "stream_unavailable_detail": "Check the aMule connection and try again.",
        "profile_settings": "Profile settings",
        "profile_intro": "Create a private manifest with your own discovery preferences.",
        "admin_password": "Admin password",
        "profile_language": "Result language",
        "search_languages": "Preferred search languages",
        "search_languages_hint": "Comma-separated language codes, for example en,es.",
        "result_limit": "Maximum results",
        "maximum_size": "Maximum file size (GB)",
        "season_packs": "Allow season packs for episodes",
        "create_profile": "Create profile manifest",
        "creating_profile": "Creating profile…",
        "profile_created": "Profile manifest created. Install this URL in Stremio.",
        "admin_disabled": "Profile management is not enabled on this instance.",
        "admin_failed": "Unable to create the profile. Check the admin password and try again.",
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
        "stream_ready": "Listo para reproducir",
        "stream_download": "Descargar con aMule",
        "stream_downloading": "Descargando en aMule",
        "stream_completed": "Archivo local completado",
        "stream_sources": "{total} fuentes ({complete} completas)",
        "stream_active_sources": "{count} fuentes activas",
        "stream_quality_fallback": "vídeo",
        "stream_no_results": "No se encontraron archivos coincidentes",
        "stream_no_results_detail": "Prueba con otro título o revisa la conexión de red de aMule.",
        "stream_unavailable": "aMule no está disponible",
        "stream_unavailable_detail": "Comprueba la conexión de aMule y vuelve a intentarlo.",
        "profile_settings": "Ajustes del perfil",
        "profile_intro": "Crea un manifest privado con tus preferencias de búsqueda.",
        "admin_password": "Contraseña de administración",
        "profile_language": "Idioma de los resultados",
        "search_languages": "Idiomas preferidos para buscar",
        "search_languages_hint": "Códigos de idioma separados por comas; por ejemplo en,es.",
        "result_limit": "Máximo de resultados",
        "maximum_size": "Tamaño máximo de archivo (GB)",
        "season_packs": "Permitir packs de temporada para episodios",
        "create_profile": "Crear manifest de perfil",
        "creating_profile": "Creando perfil…",
        "profile_created": "Manifest de perfil creado. Instala esta URL en Stremio.",
        "admin_disabled": "La gestión de perfiles no está activada en esta instancia.",
        "admin_failed": "No se pudo crear el perfil. Comprueba la contraseña e inténtalo de nuevo.",
    },
}


def resolve_locale(value: str | None) -> Locale:
    return value if value in SUPPORTED_LOCALES else "en"


def translate(locale: Locale, key: str) -> str:
    return MESSAGES[locale][key]
