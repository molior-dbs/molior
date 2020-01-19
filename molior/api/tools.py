import logging
from aiohttp.web import Response

logger = logging.getLogger("molior")


def ErrorResponse(status, msg):
    logger.info("API Error: %s", msg)
    return Response(status=status, text=msg)
