from molior.model.projectversion import ProjectVersion
from molior.model.project import Project
from molior.model.buildvariant import BuildVariant
from molior.model.architecture import Architecture


def get_buildvariants(session, basemirror_name, basemirror_version, architectures):
    """
    Gets all buildvariants matching a specific basemirror and architectures

    Args:
        basemirror_name (str): Name of the basemirror (e.g. 'stretch', 'jessie')
        basemirror_version (str): Version of the basemirror (e.g. '9.6', '8.10')
        architectures (list): Architectures (e.g. ["amd64", "armhf"])
    """
    return (
        session.query(BuildVariant)
        .join(Architecture)
        .join(ProjectVersion)
        .join(Project)
        .filter(Project.name == basemirror_name)
        .filter(ProjectVersion.name == basemirror_version)
        .filter(Architecture.name.in_(architectures))
        .all()
    )
