from ..app import app
from ..tools import ErrorResponse, OKResponse
from ..model.user import User


@app.http_get("/api2/user/{username}")
@app.authenticated
async def get_user_byname(request):
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
    username = request.match_info["username"]

    user = (
        request.cirrina.db_session.query(User)
        .filter(User.username == username)
        .first()
    )

    if not user:
        return ErrorResponse(404, "User not found")

    data = {"username": user.username, "user_id": user.id, "is_admin": user.is_admin}
    return OKResponse(data)
