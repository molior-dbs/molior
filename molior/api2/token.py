import hashlib

from secrets import token_hex
from sqlalchemy.sql import or_

from ..app import app
from ..tools import OKResponse, paginate, array2db
from ..auth import req_role

from ..model.authtoken import Authtoken
from ..model.authtoken_project import Authtoken_Project


@app.http_get("/api2/tokens")
@app.authenticated
async def get_tokens(request):
    description = request.GET.getone("description", "")
    exclude_project_id = request.GET.getone("exclude_project_id", None)

    query = request.cirrina.db_session.query(Authtoken)
    if exclude_project_id:
        query = query.outerjoin(Authtoken_Project)
        query = query.filter(or_(Authtoken_Project.project_id != exclude_project_id, Authtoken_Project.project_id.is_(None)))
    if description:
        query = query.filter(Authtoken.description.ilike("%{}%".format(description)))
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


@app.http_post("/api2/tokens")
@req_role("owner")
async def create_token(request):
    """
    Create auth token
    ---
    """
    params = await request.json()
    description = params.get("description")

    db = request.cirrina.db_session

    # FIXME: check existing description

    auth_token = token_hex(32)

    # store hashed token
    encoded = auth_token.encode()
    hashed_token = hashlib.sha256(encoded).hexdigest()

    token = Authtoken(description=description, token=hashed_token, roles=array2db(['project_create', 'mirror_create']))
    db.add(token)
    db.commit()

    return OKResponse({"token": auth_token})


@app.http_delete("/api2/tokens")
@req_role("owner")
async def delete_token(request):
    """
    Delete authtoken
    """
    params = await request.json()
    token_id = params.get("id")

    db = request.cirrina.db_session
    mappings = db.query(Authtoken_Project).filter(Authtoken_Project.authtoken_id == token_id).all()
    for mapping in mappings:
        db.delete(mapping)

    token = db.query(Authtoken).filter(Authtoken.id == token_id).first()
    db.delete(token)
    db.commit()

    return OKResponse()
