"""
This module provides the molior UserRole database model.

UserRole : sqlAlchemy table

  Constraint :
  * the primary key is on the pair user_id/project_id

  Columns :
  * user_id
  * user
  * project_id
  * project
  * role

UserRoleEnum : array of possible roles

"""
from sqlalchemy import Column, ForeignKey, Enum, PrimaryKeyConstraint
from sqlalchemy.orm import relationship

from .database import Base
from .user import User
from .project import Project

USER_ROLES = ["member", "manager", "owner"]


class UserRole(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for a UserRole.
    """

    __tablename__ = "userrole"
    __table_args__ = (PrimaryKeyConstraint("user_id", "project_id"),)

    user_id = Column(ForeignKey("molioruser.id"))
    user = relationship(User)
    project_id = Column(ForeignKey("project.id"))
    project = relationship(Project)
    role = Column(Enum(*USER_ROLES, name="role_enum"))
