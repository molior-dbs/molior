import asyncio
import sys

from mock import MagicMock, mock
sys.modules['aiofile'] = mock.MagicMock()

from molior.model.build import Build            # noqa: E402
from molior.model.maintainer import Maintainer  # noqa: F401


def test_src_build_failed():
    """
    Tests whether a sourcebuild was set to failed correctly
    """
    src_build = Build(buildtype="source")
    src_build.parent = Build(buildtype="build")

    src_build.log_state = MagicMock()
    src_build.parent.log_state = MagicMock()
    src_build.log = MagicMock()
    src_build.parent.log = MagicMock()
    src_build.logtitle = MagicMock()
    src_build.parent.logtitle = MagicMock()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(src_build.set_failed())

    assert src_build.buildstate == "build_failed"
    assert src_build.parent.buildstate == "build_failed"


def test_deb_build_failed():
    """
    Tests whether a debian build was set to failed correctly
    """
    deb_build = Build(buildtype="deb")
    deb_build.parent = Build(buildtype="source")
    deb_build.parent.parent = Build(buildtype="build")

    deb_build.log_state = MagicMock()
    deb_build.parent.log_state = MagicMock()
    deb_build.parent.parent.log_state = MagicMock()
    deb_build.log = MagicMock()
    deb_build.parent.log = MagicMock()
    deb_build.parent.parent.log = MagicMock()
    deb_build.logtitle = MagicMock()
    deb_build.parent.logtitle = MagicMock()
    deb_build.parent.parent.logtitle = MagicMock()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(deb_build.set_failed())

    assert deb_build.buildstate == "build_failed"
    assert deb_build.parent.parent.buildstate == "build_failed"


def test_src_build_publish_failed():
    """
    Tests whether a sourcebuild was set to publish failed when
    the publish failed
    """
    src_build = Build(buildtype="source")
    src_build.parent = Build(buildtype="build")

    src_build.log_state = MagicMock()
    src_build.parent.log_state = MagicMock()
    src_build.log = MagicMock()
    src_build.parent.log = MagicMock()
    src_build.logtitle = MagicMock()
    src_build.parent.logtitle = MagicMock()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(src_build.set_publish_failed())

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

    deb_build.log_state = MagicMock()
    deb_build.parent.log_state = MagicMock()
    deb_build.parent.parent.log_state = MagicMock()
    deb_build.log = MagicMock()
    deb_build.parent.log = MagicMock()
    deb_build.parent.parent.log = MagicMock()
    deb_build.logtitle = MagicMock()
    deb_build.parent.logtitle = MagicMock()
    deb_build.parent.parent.logtitle = MagicMock()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(deb_build.set_publish_failed())

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

    deb_build.log_state = MagicMock()
    deb_build.parent.log_state = MagicMock()
    deb_build.parent.parent.log_state = MagicMock()
    deb_build.log = MagicMock()
    deb_build.parent.log = MagicMock()
    deb_build.parent.parent.log = MagicMock()
    deb_build.logtitle = MagicMock()
    deb_build.parent.logtitle = MagicMock()
    deb_build.parent.parent.logtitle = MagicMock()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(deb_build.set_successful())

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

    deb_build.log_state = MagicMock()
    deb_build.parent.log_state = MagicMock()
    deb_build.parent.parent.log_state = MagicMock()
    deb_build.log = MagicMock()
    deb_build.parent.log = MagicMock()
    deb_build.parent.parent.log = MagicMock()
    deb_build.logtitle = MagicMock()
    deb_build.parent.logtitle = MagicMock()
    deb_build.parent.parent.logtitle = MagicMock()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(deb_build.set_successful())

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

    deb_build.log_state = MagicMock()
    deb_build.parent.log_state = MagicMock()
    deb_build.parent.parent.log_state = MagicMock()
    deb_build.log = MagicMock()
    deb_build.parent.log = MagicMock()
    deb_build.parent.parent.log = MagicMock()
    deb_build.logtitle = MagicMock()
    deb_build.parent.logtitle = MagicMock()
    deb_build.parent.parent.logtitle = MagicMock()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(deb_build.set_successful())

    assert deb_build.buildstate == "successful"
    assert deb_build.parent.parent.buildstate != "successful"
