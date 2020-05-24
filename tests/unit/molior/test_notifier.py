import asyncio

from urllib.parse import quote_plus
from mock import patch, MagicMock, Mock, mock_open

from molior.model.build import Build
from molior.molior.worker_notification import NotificationWorker


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
    hook.body = "[]"

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

    with patch(
            "molior.molior.notifier.Configuration") as cfg, patch(
            "molior.molior.worker_notification.trigger_hook", side_effect=asyncio.coroutine(
                lambda method, url, skip_ssl, body: None)
            ) as trigger_hook, patch(
            "molior.molior.worker_notification.app") as app, patch(
            "molior.molior.worker_notification.Session") as Session, patch(
            "molior.molior.configuration.open", mock_open(read_data="{'hostname': 'testhostname'}")):
        cfg.return_value.hostname = "localhost"

        enter = MagicMock()
        session = MagicMock()
        query = MagicMock()
        qfilter = MagicMock()
        enter.__enter__.return_value = session
        query.filter.return_value = qfilter
        qfilter.first.return_value = build

        session.query.return_value = query

        Session.return_value = enter
        Session().__enter__().query().filter().first().return_value = build

        app.websocket_broadcast = Mock(side_effect=asyncio.coroutine(lambda msg: None))
        loop = asyncio.get_event_loop()
        notification_worker = NotificationWorker()
        asyncio.ensure_future(notification_worker.run())
        loop.run_until_complete(Build.build_changed(build))

        Session.assert_called()

        trigger_hook.assert_called_with(
            "get",
            "http://nonsense.invalid/get/{}".format(quote_plus(build.version)),
            skip_ssl=True,
            body="[]",
        )
