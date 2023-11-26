import logging
import logging.handlers

logging.basicConfig(level=logging.INFO, format='molior: %(message)s')
# logging.basicConfig(level=logging.INFO, format='molior: %(message)s',
#                     handlers=[logging.handlers.SysLogHandler(address='/dev/log')])
logger = logging.getLogger("molior")
