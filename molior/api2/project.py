import hashlib
import json

from sqlalchemy.sql import or_, func
from secrets import token_hex

from ..app import app
from ..tools import ErrorResponse, OKResponse, array2db, is_name_valid, paginate, parse_int, db2array, escape_for_like
from ..auth import req_role
from ..molior.queues import enqueue_aptly

from ..model.metadata import MetaData
from ..model.project import Project
from ..model.authtoken import Authtoken
from ..model.authtoken_project import Authtoken_Project
from ..model.projectversion import ProjectVersion, find_basemirror_or_baseproject, get_projectversion, DEPENDENCY_POLICIES
from ..model.user import User
from ..model.userrole import UserRole, USER_ROLES
from ..model.projectversiondependency import ProjectVersionDependency
from ..model.sourepprover import SouRepProVer
from ..model.sourcerepository import SourceRepository


@app.http_get("/api2/projectbase/{project_name}")
@app.authenticated
async def get_project_byname(request):
    """
    Returns a project with version information.

    ---
    description: Returns information about a project.
    tags:
        - Projects
    parameters:
        - name: project_name
          in: path
          required: true
          type: string
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "404":
            description: Project not found
    """

    project_name = request.match_info["project_name"]

    project = request.cirrina.db_session.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project {} not found".format(project_name))

    data = {
        "id": project.id,
        "name": project.name,
        "description": project.description,
    }

    return OKResponse(data)


@app.http_get("/api2/projectbase/{project_name}/versions")
@app.authenticated
async def get_projectversions2(request):
    """
    Returns a list of projectversions.

    ---
    description: Returns a list of projectversions.
    tags:
        - ProjectVersions
    parameters:
        - name: project_name
          in: path
          required: true
          type: string
        - name: basemirror_id
          in: query
          required: false
          type: integer
        - name: is_basemirror
          in: query
          required: false
          type: boolean
        - name: page
          in: query
          required: false
          type: integer
        - name: page_size
          in: query
          required: false
          type: integer
        - name: per_page
          in: query
          required: false
          type: integer
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "400":
            description: Incorrect value
    """
    db = request.cirrina.db_session
    project_id = request.match_info["project_name"]
    basemirror_id = request.GET.getone("basemirror_id", None)
    is_basemirror = request.GET.getone("isbasemirror", False)
    filter_name = request.GET.getone("q", None)

    query = db.query(ProjectVersion).join(Project).filter(Project.is_mirror.is_(False), ProjectVersion.is_deleted.is_(False))
    if project_id:
        query = query.filter(or_(func.lower(Project.name) == project_id.lower(), Project.id == parse_int(project_id)))
    if filter_name:
        query = query.filter(ProjectVersion.name.ilike("%{}%".format(escape_for_like(filter_name))))
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


@app.http_post("/api2/projectbase/{project_id}/versions")
@req_role("owner")
async def create_projectversion(request):
    """
    Create a project version

    ---
    description: Create a project version
    tags:
        - ProjectVersions
    parameters:
        - name: project_id
          in: path
          required: true
          type: string
          description: The name of the project
        - name: body
          in: body
          required: true
          schema:
            type: object
            required:
              - name
              - basemirror
              - architectures
            properties:
                name:
                    type: string
                    example: "1.0.0"
                description:
                    type: string
                    example: "This version does this and that"
                basemirror:
                    type: string
                    example: "stretch/9.6"
                architectures:
                    type: array
                    items:
                        type: string
                    example: ["amd64", "armhf"]
                    # FIXME: only accept existing archs on mirror!
                dependency_policy:
                    type: string
                    description: Dependency policy
                    example: strict
                cibuilds:
                    type: boolean
                baseproject:
                    type: string
                retention_successful_builds:
                    type: integer
                retention_failed_builds:
                    type: integer
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "400":
            description: Invalid project name
    """
    params = await request.json()

    name = params.get("name")
    description = params.get("description")
    dependency_policy = params.get("dependency_policy")
    if dependency_policy not in DEPENDENCY_POLICIES:
        return ErrorResponse(400, "Wrong dependency policy2")
    cibuilds = params.get("cibuilds")
    architectures = params.get("architectures", None)
    basemirror = params.get("basemirror")
    baseproject = params.get("baseproject")
    retention_successful_builds = params.get("retention_successful_builds")
    retention_failed_builds = params.get("retention_failed_builds")
    project_id = request.match_info["project_id"]

    if retention_successful_builds is None or retention_failed_builds is None:
        db = request.cirrina.db_session

        if retention_successful_builds is None:
            retention_successful_builds = db.query(MetaData).filter_by(name='retention_successful_builds').first().value
        elif not isinstance(retention_successful_builds, int):
            return ErrorResponse(400, "Invalid retention_successful_builds. It should be an integer.",)

        if retention_failed_builds is None:
            retention_failed_builds = db.query(MetaData).filter_by(name='retention_failed_builds').first().value
        elif not isinstance(retention_failed_builds, int):
            return ErrorResponse(400, "Invalid retention_failed_builds. It should be an integer.")

        db.close()

    if not project_id:
        return ErrorResponse(400, "No project id received")
    if not name:
        return ErrorResponse(400, "No name for the projectversion recieived")
    if basemirror and not ("/" in basemirror):
        return ErrorResponse(400, "No basemirror received (format: 'name/version')")
    if baseproject and not ("/" in baseproject):
        return ErrorResponse(400, "No baseproject received (format: 'name/version')")
    if not architectures:
        return ErrorResponse(400, "No architecture received")
    if len(architectures) == 0:
        return ErrorResponse(400, "No architecture received")

    if not is_name_valid(name):
        return ErrorResponse(400, "Invalid project name")

    db = request.cirrina.db_session
    project = db.query(Project).filter(func.lower(Project.name) == project_id.lower()).first()
    if not project and isinstance(project_id, int):
        project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return ErrorResponse(400, "Project '{}' not found".format(project_id))
    if project.is_mirror:
        return ErrorResponse(400, "Cannot add projectversion to a mirror")

    projectversion = db.query(ProjectVersion).join(Project).filter(
            func.lower(ProjectVersion.name) == name.lower(), Project.id == project.id).first()
    if projectversion:
        return ErrorResponse(400, "Projectversion '{}' already exists{}".format(
                                        name,
                                        ", and is marked as deleted" if projectversion.is_deleted else ""))

    error_response, pv, bm = find_basemirror_or_baseproject(db, basemirror, baseproject)
    if error_response:
        return error_response

    for arch in architectures:
        if arch not in db2array(bm.mirror_architectures):
            return ErrorResponse(400, "Architecture not found in basemirror: {}".format(arch))

    projectversion = ProjectVersion(
            name=name,
            project=project,
            description=description,
            dependency_policy=dependency_policy,
            ci_builds_enabled=cibuilds,
            mirror_architectures=array2db(architectures),
            basemirror=bm,
            mirror_state=None,
            retention_successful_builds=retention_successful_builds,
            retention_failed_builds=retention_failed_builds,)
    db.add(projectversion)
    db.commit()

    if baseproject:
        pdep = ProjectVersionDependency(
                projectversion_id=projectversion.id,
                dependency_id=pv.id,
                use_cibuilds=False)
        db.add(pdep)
        db.commit()

    await enqueue_aptly({"init_repository": [
                bm.project.name,
                bm.name,
                projectversion.project.name,
                projectversion.name,
                architectures,
                []]})

    return OKResponse({"id": projectversion.id, "name": projectversion.name})


@app.http_put("/api2/project/{project_id}/{projectversion_id}")
@req_role("owner")
async def edit_projectversion(request):
    """
    Modify a project version

    ---
    description: Modify a project version
    tags:
        - ProjectVersions
    parameters:
        - name: project_id
          in: path
          required: true
          type: string
          description: The name of the project
        - name: projectversion_id
          in: path
          required: true
          type: string
          description: The name of the project version
        - name: body
          in: body
          required: true
          schema:
            type: object
            properties:
                description:
                    type: string
                    example: "This version does this and that"
                dependency_policy:
                    type: string
                    description: Dependency policy
                    example: strict
                retention_successful_builds:
                    type: integer
                retention_failed_builds:
                    type: integer
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "400":
            description: Projectversion not found
    """
    params = await request.json()
    description = params.get("description")
    dependency_policy = params.get("dependency_policy")
    if dependency_policy not in DEPENDENCY_POLICIES:
        return ErrorResponse(400, "Wrong dependency policy1")
    cibuilds = params.get("cibuilds")
    retention_successful_builds = params.get("retention_successful_builds")
    retention_failed_builds = params.get("retention_failed_builds")

    if retention_successful_builds is None or retention_failed_builds is None:
        db = request.cirrina.db_session

        if retention_successful_builds is None:
            retention_successful_builds = db.query(MetaData).filter_by(name='retention_successful_builds').first().value
        elif not isinstance(retention_successful_builds, int):
            return ErrorResponse(400, "Invalid retention_successful_builds. It should be an integer.")

        if retention_failed_builds is None:
            retention_failed_builds = db.query(MetaData).filter_by(name='retention_failed_builds').first().value
        elif not isinstance(retention_failed_builds, int):
            return ErrorResponse(400, "Invalid retention_failed_builds. It should be an integer.")

        db.close()

    projectversion = get_projectversion(request)
    if not projectversion:
        return ErrorResponse(400, "Projectversion not found")

    for dep in projectversion.dependents:
        if dependency_policy == "strict" and dep.basemirror_id != projectversion.basemirror_id:
            return ErrorResponse(400, "Cannot change dependency policy because strict policy demands \
                                       to use the same basemirror as all dependents")
        elif dependency_policy == "distribution" and dep.basemirror.project_id != projectversion.basemirror.project_id:
            return ErrorResponse(400, "Cannot change dependency policy because the same distribution \
                                       is required as for all dependents")

    db = request.cirrina.db_session
    projectversion.description = description
    projectversion.dependency_policy = dependency_policy
    projectversion.ci_builds_enabled = cibuilds
    projectversion.retention_successful_builds = retention_successful_builds
    projectversion.retention_failed_builds = retention_failed_builds
    db.commit()

    return OKResponse({"id": projectversion.id, "name": projectversion.name})


@app.http_delete("/api2/projectbase/{project_id}")
@req_role("owner")
async def delete_project2(request):
    """
    Removes a project from the database.

    ---
    description: Deletes a project with the given id.
    tags:
        - Projects
    parameters:
        - name: project_id
          in: path
          required: true
          type: string
          description: The name of the project
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "400":
            description: Project not found
    """
    db = request.cirrina.db_session
    project_name = request.match_info["project_id"]
    project = db.query(Project).filter_by(name=project_name).first()

    if not project:
        return ErrorResponse(400, "Project not found")

    if project.projectversions:
        return ErrorResponse(400, "Cannot delete project containing projectversions")

    query = db.query(UserRole).join(User).join(Project)
    query = query.filter(Project.id == project.id)
    userroles = query.all()
    for userrole in userroles:
        db.delete(userrole)

    tokens = db.query(Authtoken_Project).filter(Authtoken_Project.project_id == project.id).all()
    for token in tokens:
        db.delete(token)
    # FIXME: delete unreferenced project tokens

    db.delete(project)
    db.commit()
    return OKResponse("project {} deleted".format(project_name))


@app.http_get("/api2/projectbase/{project_name}/permissions")
@app.authenticated
async def get_project_users2(request):
    """
    Get project user permissions.

    ---
    description: Get project user permissions.
    tags:
        - Projects
    parameters:
        - name: project_name
          in: path
          required: true
          type: string
        - name: candidates
          in: query
          required: false
          type: boolean
        - name: q
          in: query
          required: false
          type: string
          description: Filter query
        - name: role
          in: query
          required: false
          type: string
          description: Filter role
        - name: page
          in: query
          required: false
          type: integer
        - name: page_size
          in: query
          required: false
          type: integer
        - name: per_page
          in: query
          required: false
          type: integer
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "400":
            description: Project not found
    """
    db = request.cirrina.db_session
    project_name = request.match_info["project_name"]
    candidates = request.GET.getone("candidates", None)
    if candidates:
        candidates = candidates == "true"

    project = db.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project {} not found".format(project_name))
    if project.is_mirror:
        return ErrorResponse(400, "Cannot get permissions from project which is a mirror")

    filter_name = request.GET.getone("q", None)
    filter_role = request.GET.getone("role", None)

    if candidates:
        query = db.query(User).outerjoin(UserRole).outerjoin(Project)
        query = query.filter(User.username != "admin")
        query = query.filter(or_(UserRole.project_id.is_(None), Project.id != project.id))
        if filter_name:
            query = query.filter(User.username.ilike("%{}%".format(escape_for_like(filter_name))))
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

    query = db.query(UserRole).join(User).join(Project).order_by(User.username)
    query = query.filter(Project.id == project.id)

    if filter_name:
        query = query.filter(User.username.ilike("%{}%".format(escape_for_like(filter_name))))

    if filter_role:
        for r in USER_ROLES:
            if filter_role.lower() in r:
                query = query.filter(UserRole.role == r)

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


@app.http_post("/api2/projectbase/{project_name}/permissions")
@req_role("owner")
async def add_project_users2(request):
    """
    Add permission for project

    ---
    description: Add permission for project
    tags:
        - Projects
    parameters:
        - name: project_name
          in: path
          required: true
          type: string
          description: The name of the project
        - name: body
          in: body
          required: true
          schema:
            type: object
            required:
              - username
              - role
            properties:
                username:
                    type: string
                    description: Username
                    example: "username"
                role:
                    type: string
                    description: User role, e.g. member, manager, owner, ...
                    example: "member"
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "400":
            description: Invalid role
    """
    project_name = request.match_info["project_name"]
    params = await request.json()
    username = params.get("username")
    role = params.get("role")

    if role not in ["member", "manager", "owner"]:
        return ErrorResponse(400, "Invalid role")

    if username == "admin":
        return ErrorResponse(400, "User not allowed")

    db = request.cirrina.db_session
    project = db.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project {} not found".format(project_name))
    if project.is_mirror:
        return ErrorResponse(400, "Cannot set permissions to project which is a mirror")

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


@app.http_put("/api2/projectbase/{project_name}/permissions")
@req_role("owner")
async def edit_project_users2(request):
    """
    Edit project user permissions.

    ---
    description: Edit project user permissions.
    tags:
        - Projects
    parameters:
        - name: project_name
          in: path
          required: true
          type: string
          description: The name of the project
        - name: body
          in: body
          required: true
          schema:
            type: object
            required:
              - username
              - role
            properties:
                username:
                    type: string
                    description: Username
                    example: "username"
                role:
                    type: string
                    description: User role, e.g. member, manager, owner, ...
                    example: "member"
    responses:
        "200":
            description: successful
        "400":
            description: Invalid role
    """
    project_name = request.match_info["project_name"]
    params = await request.json()
    username = params.get("username")
    role = params.get("role")

    if role not in ["member", "manager", "owner"]:
        return ErrorResponse(400, "Invalid role")

    if username == "admin":
        return ErrorResponse(400, "User not allowed")

    db = request.cirrina.db_session
    project = db.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project {} not found".format(project_name))
    if project.is_mirror:
        return ErrorResponse(400, "Cannot edit permissions of project which is a mirror")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        return ErrorResponse(404, "User not found")

    userrole = request.cirrina.db_session.query(UserRole).filter(UserRole.project_id == project.id,
                                                                 UserRole.user_id == user.id).first()
    if not userrole:
        return ErrorResponse(400, "User Role not found")
    userrole.role = role
    db.commit()

    return OKResponse()


@app.http_delete("/api2/projectbase/{project_name}/permissions")
@req_role("owner")
async def delete_project_users2(request):
    """
    Delete permissions for project

    ---
    description: Delete permissions for project
    tags:
        - Projects
    parameters:
        - name: project_name
          in: path
          required: true
          type: string
          description: The name of the project
        - name: body
          in: body
          required: true
          schema:
            type: object
            required:
              - username
            properties:
                username:
                    type: string
                    description: Username
                    example: "username"
    responses:
        "200":
            description: successful
        "400":
            description: User not allowed
    """
    project_name = request.match_info["project_name"]
    params = await request.json()
    username = params.get("username")

    if username == "admin":
        return ErrorResponse(400, "User not allowed")

    db = request.cirrina.db_session
    project = db.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project {} not found".format(project_name))
    if project.is_mirror:
        return ErrorResponse(400, "Cannot delete permissions from project which is a mirror")

    user = db.query(User).filter(User.username == username).first()
    if not user:
        return ErrorResponse(404, "User not found")

    # FIXME: check existing role

    query = request.cirrina.db_session.query(UserRole).join(User).join(Project)
    query = query.filter(User.username == username)
    query = query.filter(Project.id == project.id)
    userrole = query.first()
    db.delete(userrole)
    db.commit()

    return OKResponse()


@app.http_get("/api2/projectbase/{project_name}/tokens")
@app.authenticated
async def get_tokens(request):

    """
    Returns a list of tokens for a given project
    ---
    description: Returns a list of tokens for the specified project.
    tags:
        - Token
    parameters:
        - name: project_name
          in: path
          required: true
          type: string
          description: The name of the project
        - name: description
          in: query
          required: false
          type: string
          description: Filter tokens by description
    produces:
        - application/json
    responses:
        "200":
            description: A list of tokens successfully retrieved
        "400":
            description: Project not found
    """

    project_name = request.match_info["project_name"]
    description = request.GET.getone("description", "")

    project = request.cirrina.db_session.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project {} not found".format(project_name))

    query = request.cirrina.db_session.query(Authtoken).outerjoin(Authtoken_Project).outerjoin(Project)
    query = query.filter(Project.id == project.id)
    if description:
        query = query.filter(Authtoken.description.ilike("%{}%".format(escape_for_like(description))))
    query = paginate(request, query)
    tokens = query.all()
    data = {
        "total_result_count": query.count(),
        "results": [
            {"id": token.id, "description": token.description}
            for token in tokens
        ],
    }
    return OKResponse(data)


@app.http_post("/api2/projectbase/{project_name}/token")
@req_role("owner")
async def create_token(request):
    """
    Create project auth token
    ---
    description: Create project auth token
    tags:
        - Token
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - in: path
          name: project_name
          type: string
          required: true
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "400":
            description: Cannot create auth token for mirrors
        "404":
            description: Project not found
    """
    project_name = request.match_info["project_name"]
    params = await request.json()
    description = params.get("description")

    db = request.cirrina.db_session
    project = db.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project {} not found".format(project_name))
    if project.is_mirror:
        return ErrorResponse(400, "Cannot create auth token for mirrors")

    # FIXME: check existing

    auth_token = token_hex(32)

    # store hashed token
    encoded = auth_token.encode()
    hashed_token = hashlib.sha256(encoded).hexdigest()

    token = Authtoken(description=description, token=hashed_token)
    db.add(token)
    db.commit()
    mapping = Authtoken_Project(project_id=project.id, authtoken_id=token.id, roles=array2db(['owner']))
    db.add(mapping)
    db.commit()

    return OKResponse({"token": auth_token})


@app.http_put("/api2/projectbase/{project_name}/token")
@req_role("owner")
async def add_token(request):
    """
    Add existing auth token to project
    ---
    description: Add existing auth token to project
    tags:
        - Token
    consumes:
        - application/x-www-form-urlencoded
    parameters:
        - in: path
          name: project_name
          type: string
          required: true
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "400":
            description: Cannot create auth token for mirrors
        "404":
            description: Project not found
    """
    project_name = request.match_info["project_name"]
    params = await request.json()
    description = params.get("description")

    db = request.cirrina.db_session
    project = db.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project {} not found".format(project_name))
    if project.is_mirror:
        return ErrorResponse(400, "Cannot create auth token for mirrors")
    token = db.query(Authtoken).filter_by(description=description).first()
    if not token:
        return ErrorResponse(404, "Authtoken '{}' not found".format(description))

    # FIXME: check already added

    mapping = Authtoken_Project(project_id=project.id, authtoken_id=token.id, roles=array2db(['owner']))
    db.add(mapping)
    db.commit()

    return OKResponse()


@app.http_delete("/api2/projectbase/{project_name}/tokens")
@req_role("owner")
async def delete_project_token(request):
    """
    Delete project auth token
    ---
    description: Delete existing auth token from project
    tags:
        - Token
    parameters:
        - name: project_name
          in: path
          type: string
          required: true
          description: The name of the project
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "404":
            description: Token not found
    """
    project_name = request.match_info["project_name"]
    params = await request.json()
    token_id = params.get("id")

    db = request.cirrina.db_session
    project = db.query(Project).filter_by(name=project_name).first()
    if not project:
        return ErrorResponse(404, "Project {} not found".format(project_name))

    query = request.cirrina.db_session.query(Authtoken_Project)
    query = query.filter(Authtoken_Project.authtoken_id == token_id)
    query = query.filter(Authtoken_Project.project_id == project.id)
    token = query.first()

    if not token:
        return ErrorResponse(404, "Token not found in {}".format(project_name))

    # FIXME: delete Authtoken if not referenced by other projects
    db.delete(token)
    db.commit()

    return OKResponse()


@app.http_post("/api2/projectbase/projectversion/import")
@req_role("owner")
async def import_projectversion(request):
    """
    Imports a project version

    ---
    description: Imports a project version
    tags:
        - ProjectVersions
    parameters:
        - name: body
          in: body
          required: true
          schema:
            type: object
            required:
              - name
              - basemirror
              - architectures
            properties:
                name:
                    type: string
                    example: "1.0.0"
                description:
                    type: string
                    example: "This version does this and that"
                basemirror:
                    type: string
                    example: "stretch/9.6"
                architectures:
                    type: array
                    items:
                        type: string
                    example: ["amd64", "armhf"]
                    # FIXME: only accept existing archs on mirror!
                dependency_policy:
                    type: string
                    description: Dependency policy
                    example: strict
                cibuilds:
                    type: boolean
                baseproject:
                    type: string
    produces:
        - application/json
    responses:
        "200":
            description: successful
        "400":
            description: Invalid project name
    """
    reader = await request.multipart()

    field = await reader.next()
    if not field:
        return ErrorResponse(400, "No file was uploaded.")

    filename = field.filename
    if not filename.endswith('.json'):
        return ErrorResponse(400, "Invalid file type.")

    content = await field.read()

    try:
        json_data = json.loads(content)
    except json.JSONDecodeError:
        return ErrorResponse(400, "Failed to parse JSON data.")

    name = json_data.get('name')
    project_id = json_data.get('project_name')
    description = json_data.get('description')
    architectures = json_data.get('architectures')
    basemirror = json_data.get('basemirror')
    cibuilds = json_data.get('ci_builds_enabled')
    dependency_policy = json_data.get('dependency_policy')
    retention_successful_builds = json_data.get('retention_successful_builds')
    retention_failed_builds = json_data.get('retention_failed_builds')
    sourcerepositories = json_data.get('sourcerepositories')
    baseproject = json_data.get('baseproject', '')

    if not is_name_valid(name):
        return ErrorResponse(400, "Invalid project name")
    db = request.cirrina.db_session
    project = db.query(Project).filter(func.lower(Project.name) == project_id.lower()).first()
    if not project and isinstance(project_id, int):
        project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return ErrorResponse(400, "Project '{}' not found".format(project_id))
    if project.is_mirror:
        return ErrorResponse(400, "Cannot add projectversion to a mirror")

    projectversion = db.query(ProjectVersion).join(Project).filter(
            func.lower(ProjectVersion.name) == name.lower(), Project.id == project.id).first()
    if projectversion:
        return ErrorResponse(400, "Projectversion '{}' already exists{}".format(
                                        name,
                                        ", and is marked as deleted" if projectversion.is_deleted else ""))

    bm = None
    pv = None
    if baseproject:
        baseproject_name, baseproject_version = baseproject.split("/")
        pv = db.query(ProjectVersion).join(Project).filter(
                Project.is_basemirror.is_(False),
                func.lower(Project.name) == baseproject_name.lower(),
                func.lower(ProjectVersion.name) == baseproject_version.lower()).first()
        if not pv:
            return ErrorResponse(400, "Base project not found: {}/{}".format(baseproject_name, baseproject_version))
        bm = pv.basemirror
    else:
        basemirror_name, basemirror_version = basemirror.split("/")
        bm = db.query(ProjectVersion).join(Project).filter(
                Project.is_basemirror.is_(True),
                func.lower(Project.name) == basemirror_name.lower(),
                func.lower(ProjectVersion.name) == basemirror_version.lower()).first()
        if not bm:
            return ErrorResponse(400, "Base mirror not found: {}/{}".format(basemirror_name, basemirror_version))

    for arch in architectures:
        if arch not in db2array(bm.mirror_architectures):
            return ErrorResponse(400, "Architecture not found in basemirror: {}".format(arch))

    projectversion = ProjectVersion(
            name=name,
            project=project,
            description=description,
            dependency_policy=dependency_policy,
            ci_builds_enabled=cibuilds,
            mirror_architectures=array2db(architectures),
            basemirror=bm,
            mirror_state=None,
            retention_successful_builds=retention_successful_builds,
            retention_failed_builds=retention_failed_builds,)
    db.add(projectversion)
    db.flush()  # assign projectversion.id before creating SouRepProVer rows

    if baseproject:
        pdep = ProjectVersionDependency(
                projectversion_id=projectversion.id,
                dependency_id=pv.id,
                use_cibuilds=False)
        db.add(pdep)

    for repo_data in (sourcerepositories or []):
        repo_url = repo_data.get('url')
        repo_archs = repo_data.get('architectures', architectures)
        # filter to only archs valid for this projectversion
        repo_archs = [a for a in repo_archs if a in architectures]
        repo = db.query(SourceRepository).filter(SourceRepository.url == repo_url).first()
        if repo:
            if repo not in projectversion.sourcerepositories:
                projectversion.sourcerepositories.append(repo)
                db.flush()  # create SouRepProVer row
            srpv = db.query(SouRepProVer).filter(
                    SouRepProVer.sourcerepository_id == repo.id,
                    SouRepProVer.projectversion_id == projectversion.id).first()
            if srpv:
                srpv.architectures = array2db(repo_archs)

    db.commit()

    await enqueue_aptly({"init_repository": [
                bm.project.name,
                bm.name,
                projectversion.project.name,
                projectversion.name,
                architectures,
                []]})

    return OKResponse({"projectversion": projectversion.data(), "sourcerepositories": sourcerepositories})
