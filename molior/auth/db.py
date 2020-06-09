from sqlalchemy import func
from molior.model.user import User
from molior.model.database import Session


class AuthBackend:

    def __init__(self):
        pass

    def login(self, user, password):
        with Session() as session:
            user = session.query(User).filter(User.username == user,
                                              User.password == func.crypt(password, User.password)).first()
            if user:
                return True
        return False

    def add_user(self, username, password, email, is_admin):
        with Session() as session:
            user = User(username=username, password=func.crypt(password, func.gen_salt('bf', 8)), email=email, is_admin=is_admin)
            session.add(user)
            session.commit()

    def edit_user(self, user_id, password, email, is_admin):
        with Session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return False

            if user.username == "admin":
                return False

            user.is_admin = is_admin
            user.email = email
            if password:
                user.password = func.crypt(password, func.gen_salt('bf', 8))
            session.commit()

            # TODO : change to a multicast group
            # await app.websocket_broadcast(
            #    {
            #        "event": Event.changed.value,
            #        "subject": Subject.user.value,
            #        "changed": {"id": user_id, "is_admin": user.is_admin},
            #    }
            # )
        return True

    def delete_user(self, user_id):
        with Session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return False

            if user.username == "admin":
                return False

            session.delete(user)
            session.commit()
        return True
