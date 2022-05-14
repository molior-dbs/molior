from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Enum, Boolean
from sqlalchemy.orm import relationship, backref
from datetime import datetime

from ..app import logger
from ..tools import get_local_tz, db2array
# from .tools import check_user_role
from ..molior.notifier import Subject, Event, notify, run_hooks
from ..molior.queues import buildlog, buildlogtitle, buildlogdone

from .database import Base
from .sourcerepository import SourceRepository
from .buildtask import BuildTask
from .debianpackage import Debianpackage
from .build_debianpackage import BuildDebianpackage

BUILD_STATES = [
    "new",
    "needs_build",
    "scheduled",
    "building",
    "build_failed",
    "needs_publish",
    "publishing",
    "publish_failed",
    "successful",
    "already_exists",
    "already_failed",
    "nothing_done",
]

BUILD_TYPES = ["build", "source", "deb", "chroot", "mirror"]

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%f%z"


class Build(Base):
    __tablename__ = "build"

    id = Column(Integer, primary_key=True)
    createdstamp = Column(DateTime(timezone=True), nullable=True, default="now()")
    startstamp = Column(DateTime(timezone=True), nullable=True)
    buildendstamp = Column(DateTime(timezone=True), nullable=True)
    endstamp = Column(DateTime(timezone=True), nullable=True)
    buildstate = Column("buildstate", Enum(*BUILD_STATES, name="buildstate_enum"), default="new")
    buildtype = Column("buildtype", Enum(*BUILD_TYPES, name="buildtype_enum"), default="deb")
    version = Column(String)
    git_ref = Column(String)
    ci_branch = Column(String)
    sourcename = Column(String)
    maintainer_id = Column(ForeignKey("maintainer.id"))
    maintainer = relationship("Maintainer")
    sourcerepository_id = Column(ForeignKey("sourcerepository.id"))
    sourcerepository = relationship(SourceRepository)
    projectversion_id = Column(ForeignKey("projectversion.id"))
    projectversion = relationship("ProjectVersion")
    projectversions = Column(String)
    parent_id = Column(ForeignKey("build.id"))
    children = relationship("Build", backref=backref("parent", remote_side=[id]), remote_side=[parent_id])
    is_ci = Column(Boolean, default=False)
    builddeps = Column(String)
    buildtask = relationship(BuildTask, uselist=False)
    architecture = Column(String)
    debianpackages = relationship(Debianpackage, secondary=BuildDebianpackage)
    is_deleted = Column(Boolean, default=False)
    snapshotbuild_id = Column(Integer)

    async def log(self, msg):
        await buildlog(self.id, msg)

    async def logtitle(self, title, no_footer_newline=False, no_header_newline=True, error=False):
        await buildlogtitle(self.id, title, no_footer_newline, no_header_newline, error)

    async def logdone(self):
        await buildlogdone(self.id)

    def log_state(self, statemsg):
        build_logstate(self.id, self.buildtype, self.sourcename, self.version, statemsg)

    async def set_needs_build(self):
        self.log_state("needs build")
        self.buildstate = "needs_build"
        self.endstamp = None
        self.buildendstamp = None
        await self.build_changed()

        if self.buildtype == "deb":
            if self.parent and self.parent.parent and not self.parent.parent.buildstate == "building":
                self.parent.parent.endstamp = None
                await self.parent.parent.set_building()

    async def set_scheduled(self):
        self.log_state("scheduled")
        self.buildstate = "scheduled"
        await self.build_changed()

    async def set_building(self):
        self.log_state("building")
        self.buildstate = "building"
        now = get_local_tz().localize(datetime.now(), is_dst=None)
        self.startstamp = now
        await self.build_changed()

    async def set_failed(self):
        self.log_state("failed")
        self.buildstate = "build_failed"
        now = get_local_tz().localize(datetime.now(), is_dst=None)
        self.buildendstamp = now
        self.endstamp = now
        await self.build_changed()

        if self.buildtype == "deb":
            if not self.parent.parent.buildstate == "build_failed":
                await self.parent.parent.set_failed()
                await self.parent.parent.logtitle("Done", no_footer_newline=True, no_header_newline=False)
                await self.parent.parent.logdone()
        elif self.buildtype == "source":
            await self.parent.set_failed()

    async def set_needs_publish(self):
        self.log_state("needs publish")
        self.buildstate = "needs_publish"
        now = get_local_tz().localize(datetime.now(), is_dst=None)
        self.buildendstamp = now
        await self.build_changed()

    async def set_publishing(self):
        self.log_state("publishing")
        self.buildstate = "publishing"
        await self.build_changed()

    async def set_publish_failed(self):
        self.log_state("publishing failed")
        self.buildstate = "publish_failed"
        now = get_local_tz().localize(datetime.now(), is_dst=None)
        self.endstamp = now
        await self.build_changed()

        if self.buildtype == "deb":
            if self.parent.parent and not self.parent.parent.buildstate == "build_failed":
                await self.parent.parent.set_failed()
                await self.parent.parent.logtitle("Done", no_footer_newline=True, no_header_newline=False)
                await self.parent.parent.logdone()
        elif self.buildtype == "source":
            await self.parent.set_failed()

    async def set_successful(self):
        self.log_state("successful")
        self.buildstate = "successful"
        now = get_local_tz().localize(datetime.now(), is_dst=None)
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
                await self.parent.parent.logtitle("Done", no_footer_newline=True, no_header_newline=False)
                await self.parent.parent.logdone()

    async def set_already_exists(self):
        self.log_state("version already exists")
        self.buildstate = "already_exists"
        self.endstamp = get_local_tz().localize(datetime.now(), is_dst=None)
        await self.build_changed()

    async def set_already_failed(self):
        self.log_state("version already exists and build failed")
        self.buildstate = "already_failed"
        self.endstamp = get_local_tz().localize(datetime.now(), is_dst=None)
        await self.build_changed()

    async def set_nothing_done(self):
        self.log_state("nothing do to")
        self.buildstate = "nothing_done"
        self.endstamp = get_local_tz().localize(datetime.now(), is_dst=None)
        await self.build_changed()

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

        if self.projectversion and not self.projectversion.project.is_basemirror:
            is_locked = self.projectversion.is_locked
        else:
            # project_id = None
            is_locked = None

        if is_locked:
            return False

#        if project_id:
#            return check_user_role(web_session, db_session, project_id, ["member", "owner"])

        return True

    def data(self):
        data = {
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
            "architecture": self.architecture
        }

        if self.projectversion:
            pv = self.projectversion
            if pv.project.is_mirror:
                if self.buildtype == "mirror":
                    data.update({"architectures": db2array(pv.mirror_architectures)})
            elif self.buildtype == "deb" or self.buildtype == "chroot":
                data.update({"architecture": self.architecture})
                data.update({
                    "project": {
                        "name": pv.project.name,
                        "version": pv.name,
                        },
                    "buildvariant": {
                        "architecture": self.architecture,
                        "base_mirror": {
                            "name": pv.basemirror.project.name,
                            "version": pv.basemirror.name
                            },
                        "name": pv.basemirror.project.name + "-" + pv.basemirror.name + "/" + self.architecture
                        }
                    })

        if self.sourcerepository:
            data.update({"sourcerepository_id": self.sourcerepository.id})

        return data

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


def build_logstate(build_id, buildtype, sourcename, version, statemsg):
    prefix = buildtype
    name = sourcename
    if buildtype == "build":
        prefix = "task"
    if not build_id:
        build_id = -1
    logger.info("build-%d %s %s: %s %s", build_id, prefix, statemsg, name, version)
