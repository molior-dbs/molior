import cirrina

from .molior.server import MoliorServer

app = MoliorServer(session_type=cirrina.Server.SessionType.FILE, session_dir="/var/lib/molior/web-sessions/")
app.title = "Molior REST API Documentation"
app.description = "Documentation of the molior REST API."
app.api_version = 1
app.contact = ""

# import api handlers
from .auth.auth import Auth          # noqa: F401, E402
import molior.api.build              # noqa: E402
import molior.api.project            # noqa: E402
import molior.api.buildstate         # noqa: E402
import molior.api.mirror             # noqa: E402
import molior.api.websocket          # noqa: E402
import molior.api.auth               # noqa: E402
import molior.api.user               # noqa: E402
import molior.api.userrole           # noqa: E402
import molior.api.sourcerepository   # noqa: E402
import molior.api.projectuserrole    # noqa: E402
import molior.api.projectversion     # noqa: E402
import molior.api.info               # noqa: E402
import molior.api.status             # noqa: E402
import molior.api.upload             # noqa: E402

import molior.api2.project           # noqa: E402
import molior.api2.projectversion    # noqa: E402
import molior.api2.sourcerepository  # noqa: E402
import molior.api2.user              # noqa: E402
import molior.api2.mirror            # noqa: E402
import molior.api2.build             # noqa: E402
import molior.api2.token             # noqa: E402
import molior.api2.admin             # noqa: F401, E402
