"""Process-scoped CA bundle for urllib/Flet/torch; never disables TLS checks."""
import logging
import os
from pathlib import Path

log = logging.getLogger("jarvis.https")


def configure_https_trust() -> str:
    # Honour explicitly managed/private trust stores. Do not replace enterprise CAs.
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return "explicit"
    try:
        import certifi
        bundle = Path(certifi.where())
        if not bundle.is_file():
            raise FileNotFoundError("certifi CA bundle is missing")
    except (ImportError, OSError):
        log.warning("HTTPS: certifi недоступен; используется штатная проверка TLS")
        return "system"
    os.environ["SSL_CERT_FILE"] = str(bundle.resolve())
    return "certifi"
