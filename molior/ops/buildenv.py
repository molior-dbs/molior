from launchy import Launchy

from ..app import logger
from ..model.database import Session
from ..model.build import Build
from ..model.chroot import Chroot
from ..molior.queues import enqueue_task


async def CreateBuildEnv(chroot_id, build_id, dist,
                         name, version, arch, components, repo_url, mirror_keys):
    """
    Creates a sbuild chroot and other build environments.

    Args:
        dist (str): The distrelease
        version (str): The version
        arch (str): The architecture

    Returns:
        bool: True on success
    """

    with Session() as session:
        build = session.query(Build).filter(Build.id == build_id).first()
        if not build:
            logger.error("aptly worker: mirror build with id %d not found", build_id)
            return False

        await build.logtitle("Chroot Environment")

        await build.set_building()
        session.commit()

        logger.info("creating build environments for %s-%s-%s", dist, version, arch)
        await build.log("Creating build environments for %s-%s-%s\n\n" % (dist, version, arch))

        async def outh(line):
            await build.log("%s\n" % line)

        process = Launchy(["sudo", "run-parts", "-a", "build", "-a", dist, "-a", name,
                           "-a", version, "-a", arch, "-a", components, "-a", repo_url,
                           "-a", mirror_keys,
                           "/etc/molior/mirror-hooks.d"], outh, outh)
        await process.launch()
        ret = await process.wait()

        if not ret == 0:
            logger.error("error creating build env")
            await build.log("Error creating build environment\n")
            await build.log("\n")
            await build.logtitle("Done", no_footer_newline=True)
            await build.set_failed()
            await build.logdone()
            session.commit()
            return False

        await build.set_needs_publish()
        session.commit()

        await build.set_publishing()
        session.commit()

        process = Launchy(["sudo", "run-parts", "-a", "publish", "-a", dist, "-a", name, "-a", version, "-a", arch,
                           "/etc/molior/mirror-hooks.d"], outh, outh)
        await process.launch()
        ret = await process.wait()

        if not ret == 0:
            logger.error("error publishing build env")
            await build.log("Error publishing build environment\n")
            await build.logtitle("Done", no_footer_newline=True)
            await build.set_publish_failed()
            await build.logdone()
            session.commit()
            return False

        await build.log("\n")
        await build.logtitle("Done", no_footer_newline=True)
        await build.set_successful()
        session.commit()

        chroot = session.query(Chroot).filter(Chroot.id == chroot_id).first()
        chroot.ready = True
        session.commit()

        # Schedule builds
        args = {"schedule": []}
        await enqueue_task(args)

        return True
