import cirrina

from .molior.server import MoliorServer

app = MoliorServer(session_type=cirrina.Server.SessionType.FILE, session_dir="/var/lib/molior/web-sessions/")
app.title = "Molior REST API Documentation"
app.description = "Documentation of the molior REST API."
app.api_version = 1
app.contact = ""

# import api handlers
from .auth.auth import Auth          # noqa: F401
import molior.api.build              # noqa: F401
import molior.api.gitlab             # noqa: F401
import molior.api.bitbucket          # noqa: F401
import molior.api.project            # noqa: F401
import molior.api.buildstate         # noqa: F401
import molior.api.mirror             # noqa: F401
import molior.api.websocket          # noqa: F401
import molior.api.auth               # noqa: F401
import molior.api.user               # noqa: F401
import molior.api.userrole           # noqa: F401
import molior.api.sourcerepository   # noqa: F401
import molior.api.projectuserrole    # noqa: F401
import molior.api.projectversion     # noqa: F401
import molior.api.info               # noqa: F401
import molior.api.status             # noqa: F401
import molior.api.hook               # noqa: F401
import molior.api.upload             # noqa: F401

import molior.api2.project           # noqa: F401
import molior.api2.projectversion    # noqa: F401
import molior.api2.sourcerepository  # noqa: F401
import molior.api2.user              # noqa: F401
import molior.api2.mirror            # noqa: F401
import molior.api2.build             # noqa: F401
import molior.api2.token             # noqa: F401
import molior.api2.admin             # noqa: F401
