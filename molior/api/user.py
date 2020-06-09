from aiohttp import web

from molior.app import app
from molior.auth import Auth, req_admin
from molior.model.user import User
from molior.model.userrole import UserRole
from molior.model.project import Project
from molior.tools import paginate


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
      - name: name
        description: query to filter username
        in: query
        required: false
        type: string
      - name: email
        description: query to filter email
        in: query
        required: false
        type: string
      - name: admin
        description: return only admin if true
        in: query
        required: false
        type: boolean
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
    name = request.GET.getone("name", "")
    email = request.GET.getone("email", "")
    admin = request.GET.getone("admin", "false")

    query = request.cirrina.db_session.query(User)
    if admin.lower() == "true":
        query = query.filter(User.is_admin)
    if name:
        query = query.filter(User.username.like("%{}%".format(name)))
    if email:
        query = query.filter(User.email.like("%{}%".format(email)))

    query = query.order_by(User.username)
    query = paginate(request, query)
    users = query.all()

    data = {"total_result_count": query.count()}
    data["results"] = [
        {"id": user.id, "username": user.username, "email": user.email, "is_admin": user.is_admin}
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


@app.http_put("/api/user/{user_id}")
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

    params = await request.json()

    is_admin = params.get("is_admin")        # noqa: E221
    email    = params.get("email")           # noqa: E221
    password = params.get("password")        # noqa: E221

    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Incorrect value for user_id")

    ret = Auth().edit_user(user_id, password, email, is_admin)
    if not ret:
        return web.Response(status=400, text="Error modifying user")
    return web.Response(status=200)


@app.http_delete("/api/user/{user_id}")
@app.http_delete("/api/users/{user_id}")
@req_admin
# FIXME: req_role
async def delete_user_byid(request):
    """
    Delete a user by id.

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
      "200":
        description: Sucess
        schema:
          type: object
          properties:
            result:
              type: string
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
        return web.Response(status=400, text="Incorrect value for user_id")

    ret = Auth().delete_user(user_id)
    if not ret:
        return web.Response(status=400, text="Error deleting user")
    return web.Response(status=200)


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
    email = params.get("email")
    is_admin = params.get("is_admin", False)
    password = params.get("password")
    if not username:
        return web.Response(status=400, text="Invalid username")
    if not email:
        return web.Response(status=400, text="Invalid email")
    if not password:
        return web.Response(status=400, text="Invalid password")
    # FIXME: check if user already exists

    Auth().add_user(username, password, email, is_admin)
    return web.Response(status=200)
