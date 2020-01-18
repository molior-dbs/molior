import logging
from aiohttp.web import Response

logger = logging.getLogger("molior")


def ErrorResponse(status, msg):
    logger.notice(msg)
    return Response(status=status, text=msg)
