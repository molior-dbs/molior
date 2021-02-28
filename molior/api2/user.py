from ..app import app
from ..tools import ErrorResponse, OKResponse
from ..model.user import User


@app.http_get("/api2/user/{username}")
@app.authenticated
async def get_user_byname(request):
    """
    Return a user by its username.

    ---
    description: Return a user by its name.
    tags:
      - Users
    parameters:
      - name: username
        description: User name
        in: path
        required: true
        type: string
    responses:
      "200":
        description: Return a dict with results
        schema:
          type: object
          properties:
            username:
              type: string
            email:
              type: string
            user_id:
              type: integer
            is_admin:
              type: boolean
    """
    username = request.match_info["username"]

    user = (
        request.cirrina.db_session.query(User)
        .filter(User.username == username)
        .first()
    )

    if not user:
        return ErrorResponse(404, "User not found")

    data = {"username": user.username,
            "email": user.email,
            "id": user.id,
            "is_admin": user.is_admin}
    return OKResponse(data)
