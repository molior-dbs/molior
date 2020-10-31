from sqlalchemy.sql import or_

from ..app import app
from ..tools import ErrorResponse, OKResponse, array2db, is_name_valid, paginate, parse_int
from ..auth import req_role
from ..molior.queues import enqueue_aptly

from ..model.project import Project
from ..model.projectversion import ProjectVersion, get_projectversion
from ..model.user import User
from ..model.userrole import UserRole, USER_ROLES


@app.http_get("/api2/project/{project_name}")
@app.authenticated
async def get_project_byname(request):
    """
    Returns a project with version information.

    ---
    description: Returns information about a project.
    tags:
        - Projects
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: project_name
          in: path
          required: true
          type: string
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """

    project_name = request.match_info["project_name"]

    project = request.cirrina.db_session.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project with name {} could not be found!".format(project_name))

    data = {
        "id": project.id,
        "name": project.name,
        "description": project.description,
    }

    return OKResponse(data)


@app.http_get("/api2/project/{project_name}/versions")
@app.authenticated
async def get_projectversions2(request):
    """
    Returns a list of projectversions.

    ---
    description: Returns a list of projectversions.
    tags:
        - ProjectVersions
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: basemirror_id
          in: query
          required: false
          type: integer
        - name: is_basemirror
          in: query
          required: false
          type: bool
        - name: project_id
          in: query
          required: false
          type: integer
        - name: project_name
          in: query
          required: false
          type: string
        - name: page
          in: query
          required: false
          type: integer
        - name: page_size
          in: query
          required: false
          type: integer
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "500":
            description: internal server error
    """
    db = request.cirrina.db_session
    project_id = request.match_info["project_name"]
    basemirror_id = request.GET.getone("basemirror_id", None)
    is_basemirror = request.GET.getone("isbasemirror", False)
    filter_name = request.GET.getone("q", None)

    query = db.query(ProjectVersion).join(Project).filter(Project.is_mirror.is_(False), ProjectVersion.is_deleted.is_(False))
    if project_id:
        query = query.filter(or_(Project.name == project_id, Project.id == parse_int(project_id)))
    if filter_name:
        query = query.filter(ProjectVersion.name.like("%{}%".format(filter_name)))
    if basemirror_id:
        query = query.filter(ProjectVersion.basemirror_id == basemirror_id)
    elif is_basemirror:
        query = query.filter(Project.is_basemirror.is_(True), ProjectVersion.mirror_state == "ready")

    query = query.order_by(ProjectVersion.id.desc())

    nb_projectversions = query.count()
    query = paginate(request, query)
    projectversions = query.all()

    results = []
    for projectversion in projectversions:
        results.append(projectversion.data())

    data = {"total_result_count": nb_projectversions, "results": results}

    return OKResponse(data)


@app.http_post("/api2/project/{project_id}/versions")
@req_role("owner")
async def create_projectversion(request):
    """
    Create a Projectversion

    ---
    description: Create a Projectversion
    tags:
        - Projectversion
    consumes:
        - application/json
    parameters:
        - name: project
          in: path
          required: true
          type: string
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                name:
                    type: string
                    example: "1.0.0"
                basemirror:
                    type: string
                    example: "stretch/9.6"
                architectures:
                    type: array
                    example: ["amd64", "armhf"]
                    FIXME: only accept existing archs on mirror!
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: invalid data received
        "500":
            description: internal server error
    """
    db = request.cirrina.db_session
    params = await request.json()

    name = params.get("name")
    description = params.get("description")
    dependency_policy = params.get("dependency_policy")
    cibuilds = params.get("cibuilds")
    architectures = params.get("architectures", [])
    basemirror = params.get("basemirror")
    project_id = request.match_info["project_id"]

    if not project_id:
        return ErrorResponse(400, "No valid project id received")
    if not name:
        return ErrorResponse(400, "No valid name for the projectversion recieived")
    if not basemirror or not ("/" in basemirror):
        return ErrorResponse(400, "No valid basemirror received (format: 'name/version')")
    if not architectures:
        return ErrorResponse(400, "No valid architecture received")

    if not is_name_valid(name):
        return ErrorResponse(400, "Invalid project name!")

    basemirror_name, basemirror_version = basemirror.split("/")

    # FIXME: verify valid architectures

    project = db.query(Project).filter(Project.name == project_id).first()
    if not project:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return ErrorResponse(400, "Project '{}' could not be found".format(project_id))

    projectversion = db.query(ProjectVersion).join(Project).filter(
            ProjectVersion.name == name, Project.id == project.id).first()
    if projectversion:
        return ErrorResponse(400, "Projectversion '{}' already exists{}".format(
                                        name,
                                        ", and is marked as deleted" if projectversion.is_deleted else ""))

    basemirror = db.query(ProjectVersion).join(Project).filter(
                                    Project.id == ProjectVersion.project_id,
                                    Project.name == basemirror_name,
                                    ProjectVersion.name == basemirror_version).first()
    if not basemirror:
        return ErrorResponse(400, "Base mirror not found: {}/{}".format(basemirror_name, basemirror_version))

    projectversion = ProjectVersion(
            name=name,
            project=project,
            description=description,
            dependency_policy=dependency_policy,
            ci_builds_enabled=cibuilds,
            mirror_architectures=array2db(architectures),
            basemirror=basemirror,
            mirror_state=None)
    db.add(projectversion)
    db.commit()

    enqueue_aptly({"init_repository": [
                basemirror_name,
                basemirror_version,
                projectversion.project.name,
                projectversion.name,
                architectures]})

    return OKResponse({"id": projectversion.id, "name": projectversion.name})


@app.http_put("/api2/project/{project_id}/{projectversion_id}")
@req_role("owner")
async def edit_projectversion(request):
    """
    Modify a Projectversion

    ---
    description: Modify a Projectversion
    tags:
        - Projectversion
    consumes:
        - application/json
    parameters:
        - name: project
          in: path
          required: true
          type: string
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                name:
                    type: string
                    example: "1.0.0"
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: invalid data received
        "500":
            description: internal server error
    """
    params = await request.json()
    description = params.get("description")
    dependency_policy = params.get("dependency_policy")
    cibuilds = params.get("cibuilds")
    projectversion = get_projectversion(request)
    db = request.cirrina.db_session
    projectversion.description = description
    projectversion.dependency_policy = dependency_policy
    projectversion.ci_builds_enabled = cibuilds
    db.commit()

    return OKResponse({"id": projectversion.id, "name": projectversion.name})


@app.http_delete("/api2/project/{project_id}")
@req_role("owner")
async def delete_project2(request):
    """
    Removes a project from the database.

    ---
    description: Deletes a project with the given id.
    tags:
        - Projects
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - name: project_id
          in: path
          required: true
          type: string
    produces:
        - text/json
    responses:
        "200":
            description: successful
        "400":
            description: project name could not be found
    """
    db = request.cirrina.db_session
    project_name = request.match_info["project_id"]
    project = db.query(Project).filter_by(name=project_name).first()

    if not project:
        return ErrorResponse(400, "Project not found")

    if project.projectversions:
        return ErrorResponse(400, "Cannot delete project containing projectversions")

    query = request.cirrina.db_session.query(UserRole).join(User).join(Project)
    query = query.filter(Project.id == project.id)
    userroles = query.all()
    for userrole in userroles:
        db.delete(userrole)
    db.delete(project)
    db.commit()
    return OKResponse("project {} deleted".format(project_name))


@app.http_get("/api2/project/{project_name}/permissions")
@app.authenticated
async def get_project_users2(request):
    project_name = request.match_info["project_name"]
    candidates = request.GET.getone("candidates", None)
    if candidates:
        candidates = candidates == "true"

    project = request.cirrina.db_session.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project with name {} could not be found!".format(project_name))

    filter_name = request.GET.getone("filter_name", "")
    filter_role = request.GET.getone("filter_role", "")

    if candidates:
        query = request.cirrina.db_session.query(User).outerjoin(UserRole).outerjoin(Project)
        query = query.filter(User.username != "admin")
        query = query.filter(or_(UserRole.project_id.is_(None), Project.id != project.id))
        if filter_name:
            query = query.filter(User.username.like("%{}%".format(filter_name)))
        query = query.order_by(User.username)
        query = paginate(request, query)
        users = query.all()

        data = {
            "total_result_count": query.count(),
            "results": [
                {"id": user.id, "username": user.username}
                for user in users
            ],
        }
        return OKResponse(data)

    query = request.cirrina.db_session.query(UserRole).join(User).join(Project).order_by(User.username)

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

    query = paginate(request, query)
    roles = query.all()
    nb_roles = query.count()

    data = {
        "total_result_count": nb_roles,
        "results": [
            {"id": role.user.id, "username": role.user.username, "role": role.role}
            for role in roles
        ],
    }
    return OKResponse(data)


@app.http_post("/api2/project/{project_name}/permissions/{username}")
@req_role("owner")
async def add_project_users2(request):
    db = request.cirrina.db_session
    project_name = request.match_info["project_name"]
    username = request.match_info["username"]
    params = await request.json()
    role = params.get("role")

    if username == "admin":
        return ErrorResponse(400, "User not allowed")

    if role not in ["member", "manager", "owner"]:
        return ErrorResponse(400, "Invalid role")

    project = db.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project with name {} could not be found".format(project_name))

    user = db.query(User).filter(User.username == username).first()
    if not user:
        return ErrorResponse(404, "User not found")

    # check existing
    query = request.cirrina.db_session.query(UserRole).join(User).join(Project)
    query = query.filter(User.username == username)
    query = query.filter(Project.id == project.id)
    if query.all():
        return ErrorResponse(400, "User permission already added")

    userrole = UserRole(user_id=user.id, project_id=project.id, role=role)
    db.add(userrole)
    db.commit()

    return OKResponse()


@app.http_delete("/api2/project/{project_name}/permissions/{username}")
@req_role("owner")
async def delete_project_users2(request):
    db = request.cirrina.db_session
    project_name = request.match_info["project_name"]
    username = request.match_info["username"]

    if username == "admin":
        return ErrorResponse(400, "User not allowed")

    project = db.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project with name {} could not be found".format(project_name))

    user = db.query(User).filter(User.username == username).first()
    if not user:
        return ErrorResponse(404, "User not found")

    # check existing
    query = request.cirrina.db_session.query(UserRole).join(User).join(Project)
    query = query.filter(User.username == username)
    query = query.filter(Project.id == project.id)
    userrole = query.first()
    db.delete(userrole)
    db.commit()

    return OKResponse()
