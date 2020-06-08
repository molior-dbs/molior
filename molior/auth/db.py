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

    def add_user(self, user, password, email):
        with Session() as session:
            user = User(username=user, password=func.crypt(password, func.gen_salt('bf', 8)), email=email)
            session.add(user)
            session.commit()
