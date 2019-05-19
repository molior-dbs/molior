"""
This module provides the molior Build database
model.
"""
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Enum, Boolean
from sqlalchemy.orm import relationship, backref
import pytz
from datetime import datetime

from molior.molior.logger import get_logger
from .database import Base
from .buildorder import BuildOrder
from .sourcerepository import SourceRepository
from molior.molior.notifier import build_changed
from molior.molior.buildlogger import write_log_title

logger = get_logger()
local_tz = pytz.timezone("Europe/Zurich")

BUILD_STATES = [
    "new",
    "successful",
    "needs_build",
    "scheduled",
    "building",
    "build_failed",
    "needs_publish",
    "publishing",
    "publish_failed",
]

BUILD_TYPES = ["build", "source", "deb", "chroot", "mirror"]


class Build(Base):  # pylint: disable=too-few-public-methods
    """
    Database model for a build.
    """

    __tablename__ = "build"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    createdstamp = Column(DateTime(timezone=True), nullable=True, default="now()")
    startstamp = Column(DateTime(timezone=True), nullable=True)
    buildendstamp = Column(DateTime(timezone=True), nullable=True)
    endstamp = Column(DateTime(timezone=True), nullable=True)
    buildstate = Column(
        "buildstate", Enum(*BUILD_STATES, name="buildstate_enum"), default="new"
    )
    buildtype = Column(
        "buildtype", Enum(*BUILD_TYPES, name="buildtype_enum"), default="deb"
    )
    versiontimestamp = Column(DateTime(timezone=True))
    version = Column(String)
    git_ref = Column(String)
    ci_branch = Column(String)
    sourcename = Column(String)
    buildconfiguration_id = Column(ForeignKey("buildconfiguration.id"))
    buildconfiguration = relationship("BuildConfiguration")
    maintainer_id = Column(ForeignKey("maintainer.id"))
    maintainer = relationship("Maintainer")
    sourcerepository_id = Column(ForeignKey("sourcerepository.id"))
    sourcerepository = relationship("SourceRepository")
    projectversion_id = Column(ForeignKey("projectversion.id"))
    parent_id = Column(ForeignKey("build.id"))
    children = relationship(
        "Build", backref=backref("parent", remote_side=[id]), remote_side=[parent_id]
    )
    is_ci = Column(Boolean, default=False)
    build_after = relationship(
        "SourceRepository",
        secondary=BuildOrder,
        primaryjoin=(BuildOrder.c.build_id == id),
        secondaryjoin=(BuildOrder.c.dependency == SourceRepository.id),
    )

    def log_state(self, statemsg):
        prefix = ""
        if self.buildtype == "deb":
            name = self.sourcerepository.name
        elif self.buildtype == "source":
            prefix = "%s " % self.buildtype
            name = self.sourcerepository.name
        elif self.buildtype == "mirror":
            prefix = "%s " % self.buildtype
            name = self.sourcename
        elif self.buildtype == "chroot":
            prefix = "%s " % self.buildtype
            name = self.sourcename
        elif self.buildtype == "debootstrap":
            prefix = "%s " % self.buildtype
            name = self.sourcename
        elif self.buildtype == "build":
            prefix = "%s " % self.buildtype
            name = self.sourcename
        else:
            name = "I have no name!"
        if not self.id:
            b_id = -1
        else:
            b_id = self.id
        version = ""
        if self.version:
            version = self.version
        logger.info("%sbuild-%d %s: %s %s", prefix, b_id, statemsg, name, version)

    async def set_needs_build(self):
        self.log_state("needs build")
        self.buildstate = "needs_build"
        await build_changed(self)

        if self.buildtype == "deb":
            if not self.parent.parent.buildstate == "building":
                await self.parent.parent.set_building()

    async def set_scheduled(self):
        self.log_state("scheduled")
        self.buildstate = "scheduled"
        await build_changed(self)

    async def set_building(self):
        self.log_state("building")
        self.buildstate = "building"
        now = local_tz.localize(datetime.now(), is_dst=None)
        self.startstamp = now
        await build_changed(self)

    async def set_failed(self):
        self.log_state("failed")
        self.buildstate = "build_failed"
        now = local_tz.localize(datetime.now(), is_dst=None)
        self.buildendstamp = now
        self.endstamp = now
        await build_changed(self)

        if self.buildtype == "deb":
            if not self.parent.parent.buildstate == "build_failed":
                await self.parent.parent.set_failed()
                write_log_title(self.parent.parent.id, "Done", no_footer_newline=True, no_header_newline=False)
        elif self.buildtype == "source":
            await self.parent.set_failed()

    async def set_needs_publish(self):
        self.log_state("needs publish")
        self.buildstate = "needs_publish"
        now = local_tz.localize(datetime.now(), is_dst=None)
        self.buildendstamp = now
        await build_changed(self)

    async def set_publishing(self):
        self.log_state("publishing")
        self.buildstate = "publishing"
        await build_changed(self)

    async def set_publish_failed(self):
        self.log_state("publishing failed")
        self.buildstate = "publish_failed"
        now = local_tz.localize(datetime.now(), is_dst=None)
        self.endstamp = now
        await build_changed(self)

        if self.buildtype == "deb":
            if not self.parent.parent.buildstate == "build_failed":
                await self.parent.parent.set_failed()
                write_log_title(self.parent.parent.id, "Done", no_footer_newline=True, no_header_newline=False)
        elif self.buildtype == "source":
            await self.parent.set_failed()

    async def set_successful(self):
        self.log_state("successful")
        self.buildstate = "successful"
        now = local_tz.localize(datetime.now(), is_dst=None)
        self.endstamp = now
        await build_changed(self)

        if self.buildtype == "deb":
            # update (grand) parent build
            all_ok = True
            for other_build in self.parent.children:
                if other_build.id == self.id:
                    continue
                if other_build.buildstate != "successful":
                    all_ok = False
                    break
            if all_ok:
                await self.parent.parent.set_successful()
                write_log_title(self.parent.parent.id, "Done", no_footer_newline=True, no_header_newline=False)
