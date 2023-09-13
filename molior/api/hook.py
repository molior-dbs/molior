from aiohttp import web

from ..app import app
from ..model.hook import Hook
from ..model.sourcerepository import SourceRepository
from ..tools import parse_int, get_hook_triggers


@app.http_get("/api/hooks")
@app.authenticated
async def get_webhooks(request):
    """
    Gets webhooks

    ---
    description: Gets webhooks
    tags:
        - Hooks
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: sourcerepository_id
          in: query
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    repository_id = request.GET.getone("sourcerepository_id")

    if not repository_id:
        return web.Response(status=400, text="Invalid sourcerepository_id received")

    repo = (
        request.cirrina.db_session.query(SourceRepository)
        .filter(SourceRepository.id == repository_id)
        .first()
    )

    data = {
        "total_result_count": len(repo.hooks),
        "results": [
            {
                "id": hook.id,
                "method": hook.method,
                "body": hook.body,
                "url": hook.url,
                "triggers": get_hook_triggers(hook),
                "skip_ssl": hook.skip_ssl,
                "enabled": hook.enabled,
            }
            for hook in repo.hooks
        ],
    }

    return web.json_response(data)


@app.http_post("/api/hooks")
@app.authenticated
# FIXME: req_role
async def create_webhook(request):
    """
    Adds a new webhook

    ---
    description: Adds a new webhook
    tags:
        - Hooks
    consumes:
        - application/json
    parameters:
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                repository_id:
                    type: integer
                    example: 1
                skip_ssl:
                    type: boolean
                    example: false
                body:
                    type: string
                    example: "{ 'key': 'value' }"
                method:
                    type: string
                    example: "POST"
                url:
                    type: string
                    example: "http://localhost"
                triggers:
                    type: array
                    items:
                      type: string
                    example: ["src", "deb", "overall"]
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    params = await request.json()

    method = params.get("method")
    url = params.get("url")
    skip_ssl = params.get("skip_ssl", False)
    body = params.get("body", "")
    triggers = params.get("triggers", [])
    repository_id = parse_int(params.get("repository_id"))

    if not method:
        return web.Response(status=500, text="Invalid method given")

    if not url:
        return web.Response(status=500, text="Invalid url given")

    if not body and method != "GET":
        return web.Response(status=500, text="Invalid body given")

    if body and method == "GET":
        body = ""

    if not repository_id:
        return web.Response(status=500, text="Invalid repository given")

    sourcerepository = (
        request.cirrina.db_session.query(SourceRepository)  # pylint: disable=no-member
        .filter(SourceRepository.id == repository_id)
        .first()
    )

    if not sourcerepository:
        return web.Response(status=404, text="The given sourcrepository was not found")

    notify_src = "src" in triggers
    notify_deb = "deb" in triggers
    notify_overall = "overall" in triggers
    new_hook = Hook(
        skip_ssl=skip_ssl,
        url=url,
        body=body,
        method=method.lower(),
        notify_src=notify_src,
        notify_deb=notify_deb,
        notify_overall=notify_overall,
    )
    request.cirrina.db_session.add(new_hook)  # pylint: disable=no-member

    if new_hook not in sourcerepository.hooks:
        sourcerepository.hooks.append(new_hook)

    request.cirrina.db_session.commit()  # pylint: disable=no-member
    return web.Response(status=200, text="Hook successfully added")


@app.http_put("/api/hooks/{hook_id}")
@app.authenticated
# FIXME: req_role
async def update_hook(request):
    """
    Updates a hook

    ---
    description: Updates a webhook
    tags:
        - Hooks
    consumes:
        - application/json
    parameters:
        - name: hook_id
          in: path
          required: true
          type: integer
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                repository_id:
                    type: integer
                    example: 1
                skip_ssl:
                    type: boolean
                    example: false
                body:
                    type: string
                    example: "{ 'key': 'value' }"
                method:
                    type: string
                    example: "POST"
                url:
                    type: string
                    example: "http://localhost"
                triggers:
                    type: array
                    items:
                      type: string
                    example: ["src", "deb"]
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    hook_id = request.match_info.get("hook_id")

    params = await request.json()

    method = params.get("method")
    url = params.get("url")
    skip_ssl = params.get("skip_ssl", False)
    body = params.get("body")
    enabled = params.get("enabled")
    triggers = params.get("triggers", [])

    hook = request.cirrina.db_session.query(Hook).filter(Hook.id == hook_id).first()
    if not hook:
        return web.Response(status=404, text="Hook not found")

    if method is not None:
        hook.method = method.lower()
    if url is not None:
        hook.url = url
    if skip_ssl is not None:
        hook.skip_ssl = skip_ssl
    if body is not None:
        hook.body = body
    if enabled is not None:
        hook.enabled = enabled

    hook.notify_src = "src" in triggers
    hook.notify_deb = "deb" in triggers
    hook.notify_overall = "overall" in triggers

    request.cirrina.db_session.commit()  # pylint: disable=no-member

    return web.Response(status=200, text="Webhook updated")


@app.http_delete("/api/hooks/{hook_id}")
@app.authenticated
# FIXME: req_role
async def delete_hook(request):
    """
    Deletes a hook

    ---
    description: Deletes a webhook
    tags:
        - Hooks
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: hook_id
          in: path
          required: true
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    hook_id = request.match_info.get("hook_id")

    hook = request.cirrina.db_session.query(Hook).filter(Hook.id == hook_id).first()
    if not hook:
        return web.Response(status=404, text="Hook not found")

    request.cirrina.db_session.delete(hook)  # pylint: disable=no-member
    request.cirrina.db_session.commit()  # pylint: disable=no-member

    return web.Response(status=200, text="Webhook deleted")
