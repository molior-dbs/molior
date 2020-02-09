import logging
from aiohttp.web import Response

logger = logging.getLogger("molior")


def ErrorResponse(status, msg):
    logger.info("API Error: %s", msg)
    return Response(status=status, text=msg)


def paginate(request, query):
    page = request.GET.getone("page", None)
    page_size = request.GET.getone("page_size", None)

    if not page:
        return query

    if page:
        try:
            page = int(page)
            if page < 1:
                page = 1
        except (ValueError, TypeError):
            page = 1

    if page_size:
        try:
            page_size = int(page_size)
            if page_size < 1:
                page_size = 10
        except (ValueError, TypeError):
            page_size = 1

    return query.limit(page_size).offset((page - 1) * page_size)
