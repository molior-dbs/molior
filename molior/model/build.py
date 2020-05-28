import pytz

from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Enum, Boolean
from sqlalchemy.orm import relationship, backref
from datetime import datetime

from molior.app import logger
from molior.molior.buildlogger import write_log_title
# from molior.tools import check_user_role
from molior.molior.notifier import Subject, Event, notify, run_hooks

from .database import Base
from .sourcerepository import SourceRepository

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

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class Build(Base):
    __tablename__ = "build"

    id = Column(Integer, primary_key=True)  # pylint: disable=invalid-name
    createdstamp = Column(DateTime(timezone=True), nullable=True, default="now()")
    startstamp = Column(DateTime(timezone=True), nullable=True)
    buildendstamp = Column(DateTime(timezone=True), nullable=True)
    endstamp = Column(DateTime(timezone=True), nullable=True)
    buildstate = Column("buildstate", Enum(*BUILD_STATES, name="buildstate_enum"), default="new")
    buildtype = Column("buildtype", Enum(*BUILD_TYPES, name="buildtype_enum"), default="deb")
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
    sourcerepository = relationship(SourceRepository)
    projectversion_id = Column(ForeignKey("projectversion.id"))
    projectversion = relationship("ProjectVersion")
    parent_id = Column(ForeignKey("build.id"))
    children = relationship("Build", backref=backref("parent", remote_side=[id]), remote_side=[parent_id])
    is_ci = Column(Boolean, default=False)
    builddeps = Column(String)

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
        await self.build_changed()

        if self.buildtype == "deb":
            if not self.parent.parent.buildstate == "building":
                await self.parent.parent.set_building()

    async def set_scheduled(self):
        self.log_state("scheduled")
        self.buildstate = "scheduled"
        await self.build_changed()

    async def set_building(self):
        self.log_state("building")
        self.buildstate = "building"
        now = local_tz.localize(datetime.now(), is_dst=None)
        self.startstamp = now
        await self.build_changed()

    async def set_failed(self):
        self.log_state("failed")
        self.buildstate = "build_failed"
        now = local_tz.localize(datetime.now(), is_dst=None)
        self.buildendstamp = now
        self.endstamp = now
        await self.build_changed()

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
        await self.build_changed()

    async def set_publishing(self):
        self.log_state("publishing")
        self.buildstate = "publishing"
        await self.build_changed()

    async def set_publish_failed(self):
        self.log_state("publishing failed")
        self.buildstate = "publish_failed"
        now = local_tz.localize(datetime.now(), is_dst=None)
        self.endstamp = now
        await self.build_changed()

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
        await self.build_changed()

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

    def can_rebuild(self, web_session, db_session):
        """
        Returns if the given build can be rebuilt

        ---
        description: Returns if the given build can be rebuilt
        parameters:
            - name: build
              required: true
              type: object
            - name: session
              required: true
              type: object
        """
        is_failed = self.buildstate in ("build_failed", "publish_failed")
        if not is_failed:
            return False

        if self.buildconfiguration:
            # project_id = self.buildconfiguration.projectversions[0].project.id
            is_locked = self.buildconfiguration.projectversions[0].is_locked
        else:
            # project_id = None
            is_locked = None

        if is_locked:
            return False

#        if project_id:
#            return check_user_role(web_session, db_session, project_id, ["member", "owner"])

        return True

    def data(self):
        buildjson = {
            "id": self.id,
            "parent_id": self.parent_id,
            # circular dep "can_rebuild": self.can_rebuild(request.cirrina.web_session, request.cirrina.db_session),
            "buildstate": self.buildstate,
            "buildtype": self.buildtype,
            "startstamp": self.startstamp.strftime(DATETIME_FORMAT) if self.startstamp else "",
            "endstamp": self.endstamp.strftime(DATETIME_FORMAT) if self.endstamp else "",
            "version": self.version,
            "sourcename": self.sourcename,
            "maintainer": ("{} {}".format(self.maintainer.firstname, self.maintainer.surname)
                           if self.maintainer else ""),
            "maintainer_email": (self.maintainer.email if self.maintainer else ""),
            "git_ref": self.git_ref,
            "branch": self.ci_branch,
        }

        if self.projectversion:
            if self.projectversion.project.is_mirror:
                if self.buildtype == "mirror" or self.buildtype == "chroot":
                    buildjson.update({"architectures": self.projectversion.mirror_architectures[1:-1].split(",")})

        if self.buildconfiguration:
            buildjson.update(
                {
                    "project": {
                        "name": self.buildconfiguration.projectversions[0].project.name,
                        "id": self.buildconfiguration.projectversions[0].project.id,
                        "version": {
                            "name": self.buildconfiguration.projectversions[0].name,
                            "id": self.buildconfiguration.projectversions[0].id,
                            "is_locked": self.buildconfiguration.projectversions[0].is_locked,
                        },
                    },
                    "buildvariant": {
                        "architecture": {
                            "name": self.buildconfiguration.buildvariant.architecture.name,
                            "id": self.buildconfiguration.buildvariant.architecture.id,
                        },
                        "base_mirror": {
                            "name": self.buildconfiguration.buildvariant.base_mirror.project.name,
                            "version": self.buildconfiguration.buildvariant.base_mirror.name,
                            "id": self.buildconfiguration.buildvariant.base_mirror.id,
                        },
                        "name": self.buildconfiguration.buildvariant.name,
                    },
                }
            )
        return buildjson

    async def build_added(self):
        """
        Sends a `build_added` notification to the web clients

        Args:
            build (molior.model.build.Build): The build model.
        """
        data = self.data()
        await notify(Subject.build.value, Event.added.value, data)

    async def build_changed(self):
        """
        Sends a `build_changed` notification to the web clients

        Args:
            build (molior.model.build.Build): The build model.
        """
        data = self.data()
        await notify(Subject.build.value, Event.changed.value, data)

        # running hooks if needed
        if self.buildtype != "deb":  # only run hooks for deb builds
            return

        if (
           self.buildstate != "building"  # only send building, ok, nok
           and self.buildstate != "successful"
           and self.buildstate != "build_failed"
           and self.buildstate != "publish_failed"):
            return

        await run_hooks(self.id)
