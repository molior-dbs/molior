"""
Provides test molior core class.
"""
import asyncio
from urllib.parse import quote_plus
from mock import patch, MagicMock

from molior.molior.notifier import build_changed


def test_build_changed_url_encoding():
    """
    Test create_chroot
    """
    maintainer = MagicMock()
    maintainer.firstname.return_value = "John"
    maintainer.lastname.return_value = "Snow"

    hook = MagicMock()
    hook.enabled.return_value = True
    hook.skip_ssl = True
    hook.method = "get"
    hook.url = "http://nonsense.invalid/get/{{ build.version|urlencode }}"
    hook.body = ""

    srcrepo = MagicMock()
    srcrepo.hooks = [hook]
    srcrepo.id.return_value = 111
    srcrepo.url.return_value = "git://url"
    srcrepo.name.return_value = "srcpkg"

    build = MagicMock()
    build.maintainer.return_value = maintainer
    build.sourcerepository = srcrepo
    build.startstamp = "NOW"
    build.endstamp = "NOW"
    build.id = 1337
    build.buildtype = "deb"
    build.ci_branch = "master"
    build.git_ref = "1337"
    build.sourcename = "srcpkg"
    build.version = "0.0.0+git1-1337<>"
    build.buildstate = "successful"
    build.url = "/blah"
    build.raw_log_url = "/blub"

    with patch("molior.molior.notifier.Configuration") as cfg, patch(
        "molior.molior.notifier.trigger_hook"
    ) as trigger_hook:
        cfg.return_value.hostname = "localhost"

        loop = asyncio.get_event_loop()
        loop.run_until_complete(build_changed(build))

        trigger_hook.assert_called_with(
            "get",
            "http://nonsense.invalid/get/{}".format(quote_plus(build.version)),
            skip_ssl=True,
            body="",
        )
