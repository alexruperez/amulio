from typing import Literal

Locale = Literal["en", "es"]

SUPPORTED_LOCALES: tuple[Locale, ...] = ("en", "es")

MESSAGES: dict[Locale, dict[str, str]] = {
    "en": {
        "page_title": "Install aMulio for Stremio",
        "brand_configuration": "aMulio configuration",
        "amule_logo": "aMule logo",
        "manifest_description": "Search eD2K/Kad content and play completed files from aMule.",
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
        "install": "Open in Stremio app",
        "copy": "Copy manifest URL",
        "copied": "Copied!",
        "copy_failed": "Copy failed — select the URL",
        "install_feedback": "Opening Stremio…",
        "tip_label": "Tip:",
        "tip": (
            "this opens a Stremio deep link when the current device supports it. Otherwise, "
            "copy this URL and paste it into Stremio's addon manager. Mobile clients require "
            "an HTTPS public URL. Keep it private."
        ),
        "footer": "aMulio is a self-hosted Stremio addon powered by aMule.",
        "connected": "Connected",
        "connecting": "Connecting",
        "disconnected": "Disconnected",
        "ready": "Ready",
        "configured": "Configured",
        "limited": "Limited",
        "unavailable": "Unavailable",
        "unknown": "Unknown",
        "language": "Language",
        "english": "English",
        "spanish": "Spanish",
        "stream_ready": "Ready with aMulio",
        "stream_download": "Download with aMulio",
        "stream_downloading": "Downloading with aMulio",
        "stream_sources": "{count} sources",
        "stream_known_sources": "{count} known sources",
        "stream_quality_fallback": "video",
        "stream_no_results": "No matching files found",
        "stream_no_results_detail": "Try another title or check aMule network connectivity.",
        "stream_unavailable": "aMule is unavailable",
        "stream_unavailable_detail": "Check the aMule connection and try again.",
        "profile_settings": "Profile settings",
        "profile_intro": "Create a private manifest with your own discovery preferences.",
        "profile_management_disabled": (
            "Profile management is disabled. Ask this instance's administrator to set "
            "AMULIO_ADMIN_PASSWORD before creating a profile."
        ),
        "profile_basic": "Basic",
        "profile_search": "Search",
        "profile_advanced": "Advanced",
        "profile_stream_display": "Stream display",
        "storage_note": "Storage is managed by this self-hosted aMulio instance.",
        "admin_password": "Admin password",
        "profile_language": "aMulio language",
        "search_languages": "Preferred search languages",
        "search_languages_hint": "Comma-separated language codes, for example en,es.",
        "result_limit": "Maximum results",
        "maximum_size": "Maximum file size (GB)",
        "season_packs": "Allow season packs for episodes",
        "stream_show_size": "Show file size",
        "stream_show_sources": "Show source availability",
        "stream_show_language": "Show detected language",
        "stream_show_technical": "Show codec, HDR and release group",
        "create_profile": "Create profile manifest",
        "creating_profile": "Creating profile…",
        "profile_created": "Profile manifest created. Install this URL in Stremio.",
        "admin_disabled": "Profile management is not enabled on this instance.",
        "admin_failed": "Unable to create the profile. Check the admin password and try again.",
        "readiness_hint_disconnected": (
            "eD2K is disconnected, so remote searches may be unavailable."
        ),
        "readiness_hint_connecting": (
            "Kad is still connecting; remote results can take a few minutes to appear."
        ),
        "readiness_hint_limited": "",
        "readiness_hint_unavailable": (
            "aMule is unavailable. Check the daemon and its private amuleapi connection."
        ),
        "readiness_hint_ready": "aMule is ready for local playback and remote discovery.",
        "manager_title": "Download manager",
        "manager_subtitle": "Queue and library",
        "manager_intro": "Manage active downloads and completed shared files.",
        "manager_ingress_auth": "Home Assistant Ingress authorizes this manager session.",
        "manager_bootstrap_intro": (
            "Open the admin manager with an operator-provided management link. Its bootstrap "
            "token stays in the URL fragment and is never included in a request URL."
        ),
        "manager_bootstrap_open": "Open admin manager",
        "manager_bootstrap_copy": "Copy management link",
        "manager_bootstrap_missing": "Open the operator-provided management link first.",
        "manager_bootstrap_copied": (
            "Management link copied. Its token remains in the URL fragment."
        ),
        "manager_bootstrap_copy_failed": "Could not copy the management link.",
        "manager_load": "Load queue and library",
        "manager_connected": "Manager connected",
        "manager_refresh": "Refresh",
        "manager_loading": "Loading manager…",
        "manager_loaded": "Queue refreshed.",
        "manager_load_failed": "Could not authenticate or load the queue.",
        "manager_empty": "No active downloads.",
        "manager_selected": "{count} selected",
        "manager_pause": "Pause selected",
        "manager_resume": "Resume selected",
        "manager_cancel": "Cancel {count} downloads…",
        "manager_cancel_title": "Cancel selected downloads",
        "manager_cancel_warning": (
            "This removes the selected active downloads. Completed files are not affected."
        ),
        "manager_cancel_prompt": "Type {confirmation} to enable cancellation.",
        "manager_cancel_confirm": "Cancel downloads",
        "manager_cancel_failed": (
            "Cancellation failed. Type the exact confirmation and refresh selections."
        ),
        "manager_update_failed": "Queue update failed; refresh selections.",
        "manager_library": "Completed shared library",
        "manager_library_empty": "No completed shared files.",
        "manager_library_selected": "{count} files selected ({size})",
        "manager_delete": "Delete {count} files…",
        "manager_delete_title": "Delete selected completed files",
        "manager_delete_warning": (
            "This permanently removes the selected completed files from Incoming."
        ),
        "manager_delete_confirm": "Delete files",
        "manager_delete_failed": "Deletion failed. Refresh the library before trying again.",
        "manager_delete_completed": "Completed files deleted.",
        "manager_file_details": "Technical filename",
        "manager_network": "Network and node status",
        "manager_network_hint": (
            "eD2K and Kad reflect daemon status. Publish listener ports in Home Assistant "
            "Network if needed; this page cannot verify host mapping, NAT, or public "
            "reachability."
        ),
        "manager_network_unavailable": "Network status is unavailable.",
        "manager_action_completed": "{action} request completed.",
        "manager_pause_completed": "Pause request completed.",
        "manager_resume_completed": "Resume request completed.",
        "manager_cancel_completed": "Cancellation completed.",
    },
    "es": {
        "page_title": "Instala aMulio para Stremio",
        "brand_configuration": "Configuración de aMulio",
        "amule_logo": "Logo de aMule",
        "manifest_description": (
            "Busca contenido eD2K/Kad y reproduce archivos completados de aMule."
        ),
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
        "install": "Abrir en la app de Stremio",
        "copy": "Copiar URL del manifest",
        "copied": "¡Copiado!",
        "copy_failed": "No se pudo copiar — selecciona la URL",
        "install_feedback": "Abriendo Stremio…",
        "tip_label": "Consejo:",
        "tip": (
            "abre un enlace profundo de Stremio si el dispositivo actual lo admite. Si no, copia "
            "esta URL y pégala en el gestor de addons de Stremio. Los clientes móviles requieren "
            "una URL pública HTTPS. Mantenla privada."
        ),
        "footer": "aMulio es un addon autoalojado de Stremio impulsado por aMule.",
        "connected": "Conectado",
        "connecting": "Conectando",
        "disconnected": "Desconectado",
        "ready": "Listo",
        "configured": "Configurada",
        "limited": "Limitado",
        "unavailable": "No disponible",
        "unknown": "Desconocido",
        "language": "Idioma",
        "english": "Inglés",
        "spanish": "Español",
        "stream_ready": "Listo con aMulio",
        "stream_download": "Descargar con aMulio",
        "stream_downloading": "Descargando con aMulio",
        "stream_sources": "{count} fuentes",
        "stream_known_sources": "{count} fuentes conocidas",
        "stream_quality_fallback": "vídeo",
        "stream_no_results": "No se encontraron archivos coincidentes",
        "stream_no_results_detail": "Prueba con otro título o revisa la conexión de red de aMule.",
        "stream_unavailable": "aMule no está disponible",
        "stream_unavailable_detail": "Comprueba la conexión de aMule y vuelve a intentarlo.",
        "profile_settings": "Ajustes del perfil",
        "profile_intro": "Crea un manifest privado con tus preferencias de búsqueda.",
        "profile_management_disabled": (
            "La gestión de perfiles está desactivada. Pide al administrador de esta "
            "instancia que configure AMULIO_ADMIN_PASSWORD antes de crear un perfil."
        ),
        "profile_basic": "Básico",
        "profile_search": "Búsqueda",
        "profile_advanced": "Avanzado",
        "profile_stream_display": "Presentación de streams",
        "storage_note": "El almacenamiento lo gestiona esta instancia autoalojada de aMulio.",
        "admin_password": "Contraseña de administración",
        "profile_language": "Idioma de aMulio",
        "search_languages": "Idiomas preferidos para buscar",
        "search_languages_hint": "Códigos de idioma separados por comas; por ejemplo en,es.",
        "result_limit": "Máximo de resultados",
        "maximum_size": "Tamaño máximo de archivo (GB)",
        "season_packs": "Permitir packs de temporada para episodios",
        "stream_show_size": "Mostrar tamaño del archivo",
        "stream_show_sources": "Mostrar disponibilidad de fuentes",
        "stream_show_language": "Mostrar idioma detectado",
        "stream_show_technical": "Mostrar códec, HDR y grupo de lanzamiento",
        "create_profile": "Crear manifest de perfil",
        "creating_profile": "Creando perfil…",
        "profile_created": "Manifest de perfil creado. Instala esta URL en Stremio.",
        "admin_disabled": "La gestión de perfiles no está activada en esta instancia.",
        "admin_failed": "No se pudo crear el perfil. Comprueba la contraseña e inténtalo de nuevo.",
        "readiness_hint_disconnected": (
            "eD2K está desconectado; las búsquedas remotas podrían no estar disponibles."
        ),
        "readiness_hint_connecting": (
            "Kad sigue conectando; los resultados remotos pueden tardar unos minutos en aparecer."
        ),
        "readiness_hint_limited": "",
        "readiness_hint_unavailable": (
            "aMule no está disponible. Comprueba el daemon y su conexión privada con amuleapi."
        ),
        "readiness_hint_ready": (
            "aMule está listo para reproducir archivos locales y descubrir contenido remoto."
        ),
        "manager_title": "Gestor de descargas",
        "manager_subtitle": "Cola y biblioteca",
        "manager_intro": "Gestiona descargas activas y archivos compartidos completados.",
        "manager_ingress_auth": "Home Assistant Ingress autoriza esta sesión del gestor.",
        "manager_bootstrap_intro": (
            "Abre el gestor de administración con un enlace proporcionado por el operador. Su "
            "token de inicio permanece en el fragmento de la URL y nunca se incluye en una URL "
            "de solicitud."
        ),
        "manager_bootstrap_open": "Abrir gestor de administración",
        "manager_bootstrap_copy": "Copiar enlace de administración",
        "manager_bootstrap_missing": "Abre primero el enlace de administración proporcionado.",
        "manager_bootstrap_copied": (
            "Enlace de administración copiado. Su token permanece en el fragmento de la URL."
        ),
        "manager_bootstrap_copy_failed": "No se pudo copiar el enlace de administración.",
        "manager_load": "Cargar cola y biblioteca",
        "manager_connected": "Gestor conectado",
        "manager_refresh": "Actualizar",
        "manager_loading": "Cargando gestor…",
        "manager_loaded": "Cola actualizada.",
        "manager_load_failed": "No se pudo autenticar ni cargar la cola.",
        "manager_empty": "No hay descargas activas.",
        "manager_selected": "{count} seleccionadas",
        "manager_pause": "Pausar seleccionadas",
        "manager_resume": "Reanudar seleccionadas",
        "manager_cancel": "Cancelar {count} descargas…",
        "manager_cancel_title": "Cancelar descargas seleccionadas",
        "manager_cancel_warning": (
            "Esto elimina las descargas activas seleccionadas. Los archivos completados no se "
            "modifican."
        ),
        "manager_cancel_prompt": "Escribe {confirmation} para activar la cancelación.",
        "manager_cancel_confirm": "Cancelar descargas",
        "manager_cancel_failed": (
            "La cancelación falló. Escribe la confirmación exacta y actualiza las selecciones."
        ),
        "manager_update_failed": "La actualización de la cola falló; actualiza las selecciones.",
        "manager_library": "Biblioteca compartida completada",
        "manager_library_empty": "No hay archivos compartidos completados.",
        "manager_library_selected": "{count} archivos seleccionados ({size})",
        "manager_delete": "Eliminar {count} archivos…",
        "manager_delete_title": "Eliminar archivos completados seleccionados",
        "manager_delete_warning": (
            "Esto elimina permanentemente los archivos completados seleccionados de Incoming."
        ),
        "manager_delete_confirm": "Eliminar archivos",
        "manager_delete_failed": (
            "El borrado ha fallado. Actualiza la biblioteca antes de reintentarlo."
        ),
        "manager_delete_completed": "Archivos completados eliminados.",
        "manager_file_details": "Nombre técnico del archivo",
        "manager_network": "Estado de red y nodo",
        "manager_network_hint": (
            "eD2K y Kad reflejan el estado del daemon. Publica los puertos de escucha en "
            "Network de Home Assistant si es necesario; esta página no puede verificar el "
            "mapeo del host, NAT ni la accesibilidad pública."
        ),
        "manager_network_unavailable": "El estado de red no está disponible.",
        "manager_action_completed": "Solicitud de {action} completada.",
        "manager_pause_completed": "Solicitud de pausa completada.",
        "manager_resume_completed": "Solicitud de reanudación completada.",
        "manager_cancel_completed": "Cancelación completada.",
    },
}


def resolve_locale(value: str | None) -> Locale:
    return value if value in SUPPORTED_LOCALES else "en"


def translate(locale: Locale, key: str) -> str:
    return MESSAGES[locale][key]
