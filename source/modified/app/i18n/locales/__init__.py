"""Translation catalogs.  Portuguese is the source language, so it has no catalog of its own."""
from __future__ import annotations

from typing import Dict

_catalogs: Dict[str, Dict[str, str]] = {}

# Static imports (rather than importlib) so PyInstaller and python-for-android bundle each locale.
try:
    from app.i18n.locales import en as _en

    _catalogs["en"] = dict(_en.CATALOG)
except ImportError:  # pragma: no cover
    pass
try:
    from app.i18n.locales import ar as _ar

    _catalogs["ar"] = dict(_ar.CATALOG)
except ImportError:  # pragma: no cover
    pass
try:
    from app.i18n.locales import es as _es

    _catalogs["es"] = dict(_es.CATALOG)
except ImportError:  # pragma: no cover
    pass
try:
    from app.i18n.locales import fr as _fr

    _catalogs["fr"] = dict(_fr.CATALOG)
except ImportError:  # pragma: no cover
    pass
try:
    from app.i18n.locales import de as _de

    _catalogs["de"] = dict(_de.CATALOG)
except ImportError:  # pragma: no cover
    pass
try:
    from app.i18n.locales import tr as _tr

    _catalogs["tr"] = dict(_tr.CATALOG)
except ImportError:  # pragma: no cover
    pass
try:
    from app.i18n.locales import ru as _ru

    _catalogs["ru"] = dict(_ru.CATALOG)
except ImportError:  # pragma: no cover
    pass


def load_catalogs() -> Dict[str, Dict[str, str]]:
    """Return ``{language code: {source text: translation}}`` for every bundled locale."""
    return _catalogs
