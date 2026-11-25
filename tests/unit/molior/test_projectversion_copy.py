"""
Copy of a projectversion (ProjectVersion.copy, molior/model/projectversion.py).

Runs on an in-memory SQLite database. SQLAlchemy warnings are errors: the copy used to log
"SAWarning: Object of type <ProjectVersion> not in session, add operation along 'Project.projectversions'
will not proceed" (and the same for 'SourceRepository.projectversions') from the autoflush of the dependency loop.
"""
import importlib
import pkgutil
import warnings

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SAWarning
from sqlalchemy.orm import sessionmaker

import molior.model
from molior.model.database import Base

# all models, so that the relationships between them can be set up
for _module in pkgutil.iter_modules(molior.model.__path__):
    importlib.import_module("molior.model." + _module.name)
from molior.model.project import Project  # noqa: E402
from molior.model.projectversion import ProjectVersion  # noqa: E402
from molior.model.sourcerepository import SourceRepository  # noqa: E402
from molior.model.sourepprover import SouRepProVer  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def make_projectversion(db):
    base = ProjectVersion(name="13", project=Project(name="trixie", is_mirror=True, is_basemirror=True),
                          mirror_architectures="{amd64,arm64}")
    dep = ProjectVersion(name="1", project=Project(name="dep"), basemirror=base, dependency_policy="strict")
    repo = SourceRepository(name="pkg", url="https://git.example.com/pkg.git")
    pv = ProjectVersion(name="1", project=Project(name="proj"), basemirror=base, mirror_architectures="{amd64,arm64}",
                        sourcerepositories=[repo], dependencies=[dep])
    db.add(pv)
    db.flush()
    db.query(SouRepProVer).filter_by(projectversion_id=pv.id).one().architectures = "{amd64,arm64}"
    db.commit()
    return pv, base, dep, repo


def test_copy_without_sqlalchemy_warnings(db):
    pv, base, dep, repo = make_projectversion(db)
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        new = pv.copy(db, "2", "copy", "strict", base.id, ["amd64"], False, 1, 7)

    assert new.id and new.id != pv.id
    assert new.project is pv.project
    assert {v.name for v in pv.project.projectversions} == {"1", "2"}
    assert new.sourcerepositories == [repo]
    assert {v.id for v in repo.projectversions} == {pv.id, new.id}
    assert new.dependencies == [dep]
    row = db.query(SouRepProVer).filter_by(projectversion_id=new.id, sourcerepository_id=repo.id).one()
    assert row.architectures == "{amd64}"
    # the original is not changed
    assert db.query(SouRepProVer).filter_by(projectversion_id=pv.id).one().architectures == "{amd64,arm64}"


def test_copy_to_other_basemirror(db):
    """With another base mirror of the same distribution only the dependencies with policy distribution or any are
    copied (new_projectversion.basemirror is loaded in the loop, the new projectversion must be in the session)."""
    pv, base, dep, repo = make_projectversion(db)
    dist_dep = ProjectVersion(name="2", project=Project(name="dist"), basemirror=base, dependency_policy="distribution")
    pv.dependencies.append(dist_dep)
    base2 = ProjectVersion(name="13.1", project=base.project, mirror_architectures="{amd64,arm64}")
    db.add(base2)
    db.commit()
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        new = pv.copy(db, "2", "copy", "strict", base2.id, ["amd64", "arm64"], False, 1, 7)

    assert new.basemirror is base2
    assert new.dependencies == [dist_dep]
