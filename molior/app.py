import cirrina
import logging
import logging.handlers

logging.basicConfig(level=logging.INFO, format='molior: %(message)s',
                    handlers=[logging.handlers.SysLogHandler(address='/dev/log')])
logger = logging.getLogger("molior")

app = cirrina.Server()
app.title = "Molior REST API Documentation"
app.description = "Documentation of the molior REST API."
app.api_version = 1
app.contact = ""
