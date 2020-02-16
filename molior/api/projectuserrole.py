import logging
import sqlalchemy.exc

from aiohttp import web

from molior.app import app
from molior.model.project import Project
from molior.model.user import User
from molior.model.userrole import UserRole, USER_ROLES

from .messagetypes import Subject, Event

logger = logging.getLogger("molior")  # pylint: disable=invalid-name


@app.http_get("/api/projects/{project_id}/users")
@app.authenticated
async def get_project_users(request):
    """
    Returns all users with roles for a project.

    ---
    description: >
      Return the list of project's users with their role on the project
    tags:
      - Project UserRole
    produces:
      - application/json
    parameters:
      - name: project_id
        description: id of the project
        in: path
        required: true
        type: integer
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
        description: query to filter user username
        in: query
        required: false
        type: string
    responses:
      "200":
        description: Return a dict with results
        schema:
          type: object
          properties:
            project_name:
              type: string
            project_id:
              type: integer
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
                  role:
                    type: string
      "400":
        description: Invalid input where given
    """
    project_id = request.match_info["project_id"]
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Incorrect project_id")

    page = request.GET.getone("page", None)
    page_size = request.GET.getone("page_size", None)
    filter_name = request.GET.getone("filter_name", "")
    filter_role = request.GET.getone("filter_role", "")

    if page:
        try:
            page = int(page)
        except (ValueError, TypeError):
            page = 1
        page = 1 if page < 1 else page

    if page_size:
        try:
            page_size = int(page_size)
        except (ValueError, TypeError):
            page_size = 10
        page_size = 1 if page_size < 1 else page_size

    project = request.cirrina.db_session.query(Project).filter_by(id=project_id).first()
    if not project:
        return web.Response(status=404, text="Project not found")

    query = (
        request.cirrina.db_session.query(UserRole)
        .filter_by(project_id=project_id)
        .join(User)
        .filter(UserRole.user_id == User.id)
        .join(Project)
        .filter(UserRole.project_id == Project.id)
        .order_by(User.username)
    )

    if filter_name:
        query = query.filter(User.username.like("%{}%".format(filter_name)))

    if filter_role:
        role = None
        for i in USER_ROLES:
            if i.find(filter_role.lower()) >= 0:
                role = i
                break
        if role:
            query = query.filter(UserRole.role == role)

    if page and page_size:
        roles = query.limit(page_size).offset((page - 1) * page_size).all()
    else:
        roles = query.all()

    nb_roles = query.count()

    data = {
        "project_name": project.name,
        "project_id": project.id,
        "total_result_count": nb_roles,
        "results": [
            {"id": role.user.id, "username": role.user.username, "role": role.role}
            for role in roles
        ],
    }

    return web.json_response(data)


@app.http_get("/api/projects/{project_id}/users/{user_id}")
@app.authenticated
async def get_project_userrole(request):
    """
    Return a user/role for a project.

    ---
    description: Return the role for user_id on project_id
    tags:
      - Project UserRole
    produces:
      - application/json
    parameters:
      - name: project_id
        description: id of the project
        in: path
        required: true
        type: integer
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
            role:
              type: string
      "400":
        description: Invalid input where given
    """
    project_id = request.match_info["project_id"]
    user_id = request.match_info["user_id"]
    data = {"role": None}

    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Incorrect project_id")
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Incorrect user_id")

    project = request.cirrina.db_session.query(Project).filter_by(id=project_id).first()
    if not project:
        return web.Response(status=404, text="Project not found")

    if (user_id == -1) and ("username" in request.cirrina.web_session):
        user = (
            request.cirrina.db_session.query(User)
            .filter(User.username == request.cirrina.web_session["username"])
            .first()
        )
    else:
        user = request.cirrina.db_session.query(User).filter_by(id=user_id).first()
    if not user:
        return web.Response(status=404, text="User not found")

    rolerec = (
        request.cirrina.db_session.query(UserRole)
        .filter_by(project=project, user=user)
        .first()
    )
    if rolerec:
        data["role"] = rolerec.role

    return web.json_response(data)


@app.http_put("/api/projects/{project_id}/users/{user_id}")
@app.req_role("owner")
async def upsert_project_user_role(request):
    """
    Set/update a user role for a project.

    ---
    description: Set or update role for user_id on project_id
    tags:
      - Project UserRole
    produces:
      - application/json
    parameters:
      - name: project_id
        description: id of the project
        in: path
        required: true
        type: integer
      - name: user_id
        description: id of the user
        in: path
        required: true
        type: integer
      - name: role
        description: role to set
        in: query
        required: false
        type: string
    responses:
      "200":
        description: Return a dict with result
        schema:
          type: object
          properties:
            result:
              type: string
      "400":
        description: Invalid input where given
    """

    project_id = request.match_info["project_id"]
    user_id = request.match_info["user_id"]

    params = await request.json()
    user_role = params.get("role", "member")

    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Incorrect project_id")
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Incorrect user_id")

    project = request.cirrina.db_session.query(Project).filter_by(id=project_id).first()
    if not project:
        return web.Response(status=404, text="Project not found")

    user = request.cirrina.db_session.query(User).filter_by(id=user_id).first()
    if not user:
        return web.Response(status=404, text="User not found")

    rolerec = (
        request.cirrina.db_session.query(UserRole)
        .filter_by(project_id=project.id, user_id=user.id)
        .first()
    )

    if rolerec:
        rolerec.role = user_role
    else:
        request.cirrina.db_session.add(
            UserRole(user_id=user_id, project_id=project_id, role=user_role)
        )
    data = {
        "result": "{u} is now {r} on {p}".format(
            u=user.username, r=user_role, p=project.name
        )
    }

    try:
        request.cirrina.db_session.commit()
    except sqlalchemy.exc.DataError:
        request.cirrina.db_session.rollback()
        return web.Response(status=500, text="Database error")

    # TODO : change to a multicast group
    await app.websocket_broadcast(
        {
            "event": Event.changed.value,
            "subject": Subject.userrole.value,
            "changed": {"id": user_id, "project_id": project_id, "role": user_role},
        }
    )

    return web.json_response(data)


@app.http_delete("/api/projects/{project_id}/users/{user_id}")
@app.req_role("owner")
async def remove_project_user(request):
    """
    Remove a user role for a project.

    ---
    description: Remove role for user_id from project_id
    tags:
      - Project UserRole
    produces:
      - application/json
    parameters:
      - name: project_id
        description: id of the project
        in: path
        required: true
        type: integer
      - name: user_id
        description: id of the user
        in: path
        required: true
        type: integer
    responses:
      "200":
        description: Return a dict with result
        schema:
          type: object
          properties:
            result:
              type: string
      "400":
        description: Invalid input where given
    """
    project_id = request.match_info["project_id"]
    user_id = request.match_info["user_id"]
    try:
        project_id = int(project_id)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Incorrect project_id")
    try:
        user_id = int(user_id)
    except (ValueError, TypeError):
        return web.Response(status=400, text="Incorrect user_id")

    project = request.cirrina.db_session.query(Project).filter_by(id=project_id).first()
    if not project:
        return web.Response(status=404, text="Project not found")

    user = request.cirrina.db_session.query(User).filter_by(id=user_id).first()
    if not user:
        return web.Response(status=404, text="User not found")

    rolerec = (
        request.cirrina.db_session.query(UserRole)
        .filter_by(project_id=project.id, user_id=user.id)
        .first()
    )

    if not rolerec:
        return web.Response(status=400, text="No role to delete")

    (
        request.cirrina.db_session.query(UserRole)
        .filter_by(project_id=project.id, user_id=user.id)
        .delete()
    )
    try:
        request.cirrina.db_session.commit()
    except sqlalchemy.exc.DataError:
        request.cirrina.db_session.rollback()
        return web.Response(status=500, text="Database error")
    data = {"result": "{u} is removed from {p}".format(u=user.username, p=project.name)}

    # TODO : change to a multicast group
    await app.websocket_broadcast(
        {
            "event": Event.removed.value,
            "subject": Subject.userrole.value,
            "changed": {"id": user_id, "project_id": project_id},
        }
    )

    return web.json_response(data)
