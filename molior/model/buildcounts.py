"""
Build counts for the project and project version lists.

A top level build counts for a project version if one of its deb or source builds has projectversion_id
set to that version (top level builds themselves have no reliable projectversion_id). The children point to
their top level build with toplevel_id, so this is count(DISTINCT toplevel_id), split by is_ci.
Deleted child builds are not counted. One query for all the ids of a page, using the index
build (projectversion_id, id) (upgrade-67).
"""
from sqlalchemy import text

# counts of a version or project without builds
NO_BUILDS = (0, 0)

_PV_COUNTS = text("""
SELECT projectversion_id,
       count(DISTINCT toplevel_id) FILTER (WHERE NOT coalesce(is_ci, false)),
       count(DISTINCT toplevel_id) FILTER (WHERE is_ci)
FROM build
WHERE projectversion_id = ANY(:ids) AND buildtype IN ('deb', 'source') AND NOT is_deleted
GROUP BY projectversion_id
""")

_PROJECT_COUNTS = text("""
SELECT pv.project_id,
       count(DISTINCT b.toplevel_id) FILTER (WHERE NOT coalesce(b.is_ci, false)),
       count(DISTINCT b.toplevel_id) FILTER (WHERE b.is_ci)
FROM build b JOIN projectversion pv ON pv.id = b.projectversion_id
WHERE pv.project_id = ANY(:ids) AND b.buildtype IN ('deb', 'source') AND NOT b.is_deleted
GROUP BY pv.project_id
""")


def _counts(db, query, ids):
    ids = sorted({i for i in ids if i is not None})
    counts = {i: NO_BUILDS for i in ids}
    if not ids:
        return counts
    for row_id, builds, cibuilds in db.execute(query, {"ids": ids}):
        counts[row_id] = (builds, cibuilds)
    return counts


def projectversion_build_counts(db, projectversion_ids):
    """Returns {projectversion_id: (top level builds, top level CI builds)} for all given ids."""
    return _counts(db, _PV_COUNTS, projectversion_ids)


def project_build_counts(db, project_ids):
    """Returns {project_id: (top level builds, top level CI builds)} for all given ids, each top level build once."""
    return _counts(db, _PROJECT_COUNTS, project_ids)
