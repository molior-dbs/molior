from sqlalchemy import Column, String, Integer, func
from sqlalchemy.ext.hybrid import hybrid_property

from .database import Base


class Maintainer(Base):
    __tablename__ = "maintainer"

    id = Column(Integer, primary_key=True)
    firstname = Column(String)
    surname = Column(String)
    email = Column(String)

    @hybrid_property
    def fullname(self):
        return "{} {}".format(self.firstname, self.surname)

    @fullname.expression
    def fullname(cls):
        return func.concat(cls.firstname, " ", cls.surname)
