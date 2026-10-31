"""Package modèles. Importer n'importe quel sous-module enregistre TOUTES les tables.

Évite les FK cross-module non résolues (ex. school.organization_id) quand un test
ne crée que quelques tables : tout le metadata est peuplé d'un coup.
"""
from . import base  # noqa: F401
from . import competency  # noqa: F401
from . import curriculum  # noqa: F401
from . import item  # noqa: F401
from . import measurement  # noqa: F401
from . import org  # noqa: F401
from . import session  # noqa: F401
from . import audit  # noqa: F401
from . import token  # noqa: F401
from . import checkin  # noqa: F401
from . import plan  # noqa: F401
from . import lesson  # noqa: F401
