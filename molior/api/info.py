from aiohttp import web

from molior.app import app
from molior.molior.configuration import Configuration


@app.http_get("/api/info/aptlyhostname")
@app.authenticated
async def get_aptlyhostname(*_):
    """
    Returns the aptly hostname from the molior
    config file

    ---
    description: Returns the aptly hostname from the molior config file
    tags:
        - Info
    consumes:
        - application/x-www-form-urlencoded
    responses:
        "200":
            description: successful
    """
    config = Configuration()
    return web.Response(text=config.aptly.get("host"))
