import asyncio
import importlib
import pkgutil

from unittest.mock import AsyncMock, MagicMock

import molior.model

# all models, so that the relationships between them can be set up (also when this file runs alone)
for _module in pkgutil.iter_modules(molior.model.__path__):
    importlib.import_module("molior.model." + _module.name)
from molior.model.build import Build  # noqa: E402


def logmock(build):
    build.log_state = MagicMock()
    build.parent.log_state = MagicMock()
    if build.parent.parent:
        build.parent.parent.log_state = MagicMock()
    build.log = AsyncMock(return_value=None)
    build.parent.log = AsyncMock(return_value=None)
    if build.parent.parent:
        build.parent.parent.log = AsyncMock(return_value=None)
    build.logtitle = AsyncMock(return_value=None)
    build.parent.logtitle = AsyncMock(return_value=None)
    if build.parent.parent:
        build.parent.parent.logtitle = AsyncMock(return_value=None)


def test_src_build_failed():
    """
    Tests whether a sourcebuild was set to failed correctly
    """
    src_build = Build(buildtype="source")
    src_build.parent = Build(buildtype="build")

    logmock(src_build)

    asyncio.run(src_build.set_failed())

    assert src_build.buildstate == "build_failed"
    assert src_build.parent.buildstate == "build_failed"


def test_deb_build_failed():
    """
    Tests whether a debian build was set to failed correctly
    """
    deb_build = Build(buildtype="deb")
    deb_build.parent = Build(buildtype="source")
    deb_build.parent.parent = Build(buildtype="build")

    logmock(deb_build)

    asyncio.run(deb_build.set_failed())

    assert deb_build.buildstate == "build_failed"
    assert deb_build.parent.parent.buildstate == "build_failed"


def test_src_build_publish_failed():
    """
    Tests whether a sourcebuild was set to publish failed when
    the publish failed
    """
    src_build = Build(buildtype="source")
    src_build.parent = Build(buildtype="build")

    logmock(src_build)

    asyncio.run(src_build.set_publish_failed())

    assert src_build.buildstate == "publish_failed"
    assert src_build.parent.buildstate == "build_failed"


def test_deb_build_publish_failed():
    """
    Tests whether a debian was set to publish failed when
    the publish failed
    """
    deb_build = Build(buildtype="deb")
    deb_build.parent = Build(buildtype="source")
    deb_build.parent.parent = Build(buildtype="build")

    logmock(deb_build)

    asyncio.run(deb_build.set_publish_failed())

    assert deb_build.buildstate == "publish_failed"
    assert deb_build.parent.parent.buildstate == "build_failed"


def test_deb_build_successful_only_build():
    """
    Tests whether a debian was set to successful correctly
    """
    deb_build = Build(id=1337, buildtype="deb")
    deb_build.parent = Build(buildtype="source")
    deb_build.parent.parent = Build(buildtype="build")
    deb_build.parent.children = [deb_build]

    logmock(deb_build)

    asyncio.run(deb_build.set_successful())

    assert deb_build.buildstate == "successful"
    assert deb_build.parent.parent.buildstate == "successful"


def test_deb_build_successful_all_successful():
    """
    Tests whether a debian was set to successful correctly
    with multiple builds
    """
    deb_build = Build(
        id=1337,
        buildtype="deb"
    )
    deb_build.parent = Build(buildtype="source")
    deb_build.parent.parent = Build(buildtype="build")

    other_build = Build(buildtype="source")
    other_build.buildstate = "successful"

    deb_build.parent.children = [deb_build, other_build]

    logmock(deb_build)

    asyncio.run(deb_build.set_successful())

    assert deb_build.buildstate == "successful"
    assert deb_build.parent.parent.buildstate == "successful"


def test_deb_build_successful_other_failed():
    """
    Tests whether a debian was set to successful correctly
    with multiple builds and the other build has failed
    """
    deb_build = Build(
        id=1337,
        buildtype="deb"
    )
    deb_build.parent = Build(buildtype="source")
    deb_build.parent.parent = Build(buildtype="build")

    other_build = Build(buildtype="source")
    other_build.buildstate = "build_failed"

    deb_build.parent.children = [deb_build, other_build]

    logmock(deb_build)

    asyncio.run(deb_build.set_successful())

    assert deb_build.buildstate == "successful"
    assert deb_build.parent.parent.buildstate != "successful"
