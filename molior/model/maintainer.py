"""
This module provides the molior Maintainer database
model.
"""
from sqlalchemy import Column, String, Integer, func
from sqlalchemy.ext.hybrid import hybrid_property

from .database import Base


class Maintainer(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for a maintainer.
    """

    __tablename__ = "maintainer"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    firstname = Column(String)
    surname = Column(String)
    email = Column(String)

    @hybrid_property
    def fullname(self):
        """
        Returns the full name of the maintainer. Combined
        of firstname and surname
        """
        return "{firstname} {surname}".format(
            firstname=self.firstname, surname=self.surname
        )

    @fullname.expression
    def fullname(cls):  # pylint: disable=no-self-argument
        """
        Returns the full name of the maintainer. Combined
        of firstname and surname
        """
        return func.concat(cls.firstname, " ", cls.surname)
