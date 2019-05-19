"""
This module provides the molior Chroot
database model.
"""
from sqlalchemy import Column, Integer, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from .database import Base
from .buildvariant import BuildVariant


class Chroot(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for a chroot.
    """

    __tablename__ = "chroot"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    buildvariant_id = Column(ForeignKey("buildvariant.id"))
    buildvariant = relationship(BuildVariant)
    ready = Column(Boolean)
