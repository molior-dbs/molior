import sqlalchemy.exc

from aiohttp import web

from molior.app import app
from molior.auth import Auth, req_admin
from molior.model.user import User
from molior.model.userrole import UserRole
from molior.model.project import Project
from molior.tools import paginate
from molior.molior.notifier import Subject, Event


@app.http_get("/api/users")
@app.authenticated
async def get_users(request):
    """
    Return a list of users.

    ---
    description: Returns a list of users.
    tags:
      - Users
    produces:
      - application/json
    parameters:
      - name: page
        description: page number
        in: query
        required: false
        type: integer
      - name: page_size
        description: page size
        in: query
        required: false
        type: integer
      - name: q
        description: query to filter username
        in: query
        required: false
        type: string
      - name: filter_admin
        description: return only admin if true
        in: query
        required: false
        type: boolean
      - name: count_only
        description: If the items should only be counted
        type: boolean
        required: false
    produces:
      - text/json
    responses:
      "200":
        description: successful
        schema:
          type: object
          properties:
            total_result_count:
              type: integer
            resuls:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  username:
                    type: string
                  is_admin:
                    type: boolean
      "400":
        description: invalid input where given
    """
    filter_name = request.GET.getone("q", "")
    filter_admin = request.GET.getone("filter_admin", "false")

    try:
        count_only = request.GET.getone("count_only").lower() == "true"
    except (ValueError, KeyError):
        count_only = False

    query = request.cirrina.db_session.query(User)
    if filter_admin.lower() == "true":
        query = query.filter(User.is_admin)
    if filter_name:
        query = query.filter(User.username.like("%{}%".format(filter_name)))

    nb_users = query.count()
    query = query.order_by(User.username)
    query = paginate(request, query)
    users = query.all()

    data = {"total_result_count": nb_users}
    if not count_only:
        data["results"] = [
            {"id": user.id, "username": user.username, "is_admin": user.is_admin}
            for user in users
        ]

    return web.json_response(data)


@app.http_get("/api/users/{user_id}")
@app.authenticated
async def get_user_byid(request):
    """
    Return a user by its id.

    ---
    description: Get a user
    tags:
      - Users
    parameters:
      - name: user_id
        description: id of the user
        in: path
        required: true
        type: integer
    responses:
      "200":
        description: Return a dict with results
        schema:
          type: object
          properties:
            username:
              type: string
            user_id:
              type: integer
            is_admin:
              type: boolean
      "400":
        description: Invalid input where given
    """
    user_id = request.match_info["user_id"]
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return web.Response(text="Incorrect value for user_id", status=400)

    currentuser = (
        request.cirrina.db_session.query(User)
        .filter(User.username == request.cirrina.web_session["username"])
        .first()
    )

    if user_id == -1 or not currentuser.is_admin:
        user = currentuser
    else:
        user = request.cirrina.db_session.query(User).filter_by(id=user_id).first()

    if not user:
        return web.Response(status=404, text="User not found")

    data = {"username": user.username, "user_id": user.id, "is_admin": user.is_admin}
    return web.json_response(data)


@app.http_put("/api/users/{user_id}")
@req_admin
async def put_user_byid(request):
    """
    Update a user by id (not yet implemented).

    ---
    description: Change a user
    tags:
      - Users
    parameters:
      - name: user_id
        description: id of the user
        in: path
        required: true
        type: integer
      - name: is_admin
        description: set admin or not
        in: query
        required: false
        type: boolean
    responses:
      "200":
        description: Sucess
        schema:
          type: object
          properties:
            result:
              type: string
      "204":
        description: Nothing to change
      "400":
        description: Invalid parameter
      "404":
        description: User not found
      "500":
        description: Database problem
    """
    user_id = request.match_info["user_id"]
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return web.Response(text="Incorrect value for user_id", status=400)

    user = request.cirrina.db_session.query(User).filter_by(id=user_id).first()
    if not user:
        return web.Response(status=404, text="User not found")

    if user.username == "admin":
        return web.Response(status=400, text="Cannot change admin")

    is_admin = request.GET.getone("is_admin", None)  # str "true" or "flase"
    if not is_admin:  # if None
        return web.Response(text="Nothing to change", status=204)

    if is_admin.lower() == "true":
        user.is_admin = True
        data = {"result": "{u} is now admin ".format(u=user.username)}
    elif is_admin.lower() == "false":
        user.is_admin = False
        data = {"result": "{u} is no longer admin ".format(u=user.username)}

    try:
        request.cirrina.db_session.commit()  # pylint: disable=no-member
    except sqlalchemy.exc.DataError:
        request.cirrina.db_session.rollback()  # pylint: disable=no-member
        return web.Response(status=500, text="Database error")

    # TODO : change to a multicast group
    await app.websocket_broadcast(
        {
            "event": Event.changed.value,
            "subject": Subject.user.value,
            "changed": {"id": user_id, "is_admin": user.is_admin},
        }
    )

    return web.json_response(data)


@app.http_delete("/api/users/{user_id}")
@req_admin
# FIXME: req_role
async def delete_user_byid(*_):
    """
    Delete a user by id (not yet implemented).

    ---
    description: Delete a user
    tags:
      - Users
    parameters:
      - name: user_id
        description: id of the user
        in: path
        required: true
        type: integer
    responses:
      "501":
        description: Sorry, not implememted
    """
    return web.Response(text="PUT project not implemented", status=501)


@app.http_get("/api/users/{user_id}/roles")
@req_admin
async def get_user_roles(request):
    """
    Return a list of project/role for a user.

    ---
    description: Return a list of user project roles
    tags:
      - Project UserRole
    parameters:
      - name: user_id
        description: id of the user
        required: true
        type: integer
    responses:
      "200":
        description: Return a dict with results
        schema:
          type: object
          properties:
            total_result_count:
              type: integer
            resuls:
              type: array
              items:
                type: object
                properties:
                  id:
                    type: integer
                  username:
                    type: string
                  is_admin:
                    type: boolean
      "400":
        description: Invalid input where given
    """

    user_id = request.match_info["user_id"]
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Incorrect user_id")

    user = request.cirrina.db_session.query(User).filter_by(id=user_id).first()
    if not user:
        return web.Response(status=404, text="User not found")

    data = {
        "username": user.username,
        "user_id": user.id,
        "roles": {"owner": [], "member": [], "manager": []},  # FIXME : use USER_ROLES
    }

    roles = (
        request.cirrina.db_session.query(UserRole)
        .filter_by(user_id=user_id)
        .join(Project)
        .filter(UserRole.project_id == Project.id)
        .order_by(Project.name)
        .values(UserRole.role, Project.id, Project.name)
    )

    for role in roles:
        data["roles"][role.role].append({"id": role.id, "name": role.name})

    return web.json_response(data)


@app.http_post("/api/users")
@req_admin
async def create_user(request):
    """
    Create a user

    ---
    description: Create a user
    tags:
      - Users
    consumes:
      - application/json
    parameters:
      - name: username
        description: login name
        in: path
        required: true
        type: string
      - name: password
        description: login password
        in: path
        required: true
        type: password
      - name: email
        description: contact email
        in: path
        required: true
        type: string
      - name: is_admin
        description: set admin or not
        in: query
        required: false
        type: boolean
    responses:
      "200":
        description: Sucess
        schema:
          type: object
          properties:
            result:
              type: string
      "204":
        description: Nothing to change
      "400":
        description: Invalid parameter
      "404":
        description: User not found
      "500":
        description: Database problem
    """
    params = await request.json()

    username = params.get("name")
    password = params.get("password")
    email = params.get("email")
    if not username:
        return web.Response(status=400, text="Invalid username")
    if not password:
        return web.Response(status=400, text="Invalid password")
    if not email:
        return web.Response(status=400, text="Invalid email")

    Auth().add_user(username, password)
    return web.Response(status=200)
