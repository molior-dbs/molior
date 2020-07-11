from pathlib import Path
from sqlalchemy import Column, String, Integer, Enum
from sqlalchemy.orm import relationship

# Needed imports for relatioships
import molior.model.projectversion  # pylint: disable=unused-import
import molior.model.hook  # noqa: F401, pylint: disable=unused-import

from molior.app import logger
from .database import Base
from .sourcerepositoryhook import SourceRepositoryHook

from molior.molior.configuration import Configuration

REPO_STATES = ["new", "cloning", "error", "ready", "busy"]
DEFAULT_CWD = "/var/lib/molior"


class SourceRepository(Base):
    __tablename__ = "sourcerepository"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    url = Column(String)
    state = Column("state", Enum(*REPO_STATES, name="sourcerepositorystate_enum"), default="new")
    projectversions = relationship("ProjectVersion", secondary="sourcerepositoryprojectversion")
    hooks = relationship("Hook", secondary=SourceRepositoryHook)

    def __init__(self, url):
        self.url = url

    @property
    def path(self):
        """
        Returns the top level path of the soucrerepo.
        E.g. /var/lib/molior/repositories/1

        Returns:
            Path: The sourcerepo's top level path.
        """
        cfg = Configuration()
        cwd = cfg.working_dir if cfg.working_dir else DEFAULT_CWD
        return Path(cwd, "repositories", str(self.id))

    @property
    def src_path(self):
        """
        Returns the path to the git repository.
        E.g. /var/lib/molior/repositories/1/myrepo

        Returns:
            Path: The sourcerepo's git repo path.
        """
        return self.path / self.name

    def log_state(self, statemsg):
        logger.info("repository %s (%d): %s", self.name, self.id, statemsg)

    def set_new(self):
        self.log_state("created")
        self.state = "new"

    def set_cloning(self):
        self.log_state("cloning")
        self.state = "cloning"

    def set_error(self):
        self.log_state("git error")
        self.state = "error"

    def set_ready(self):
        self.log_state("ready")
        self.state = "ready"

    def set_busy(self):
        self.log_state("busy")
        self.state = "busy"
