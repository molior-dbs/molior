from launchy import Launchy

from ..logger import logger
from ..model.database import Session
from ..model.build import Build
from ..model.chroot import Chroot
from ..molior.queues import enqueue_task, buildlog


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
        await build.parent.set_building()
        session.commit()

        logger.info("creating build environments for %s-%s-%s", dist, version, arch)
        await build.log("Creating build environments for %s-%s-%s\n\n" % (dist, version, arch))

        build_id = build.id

        async def outh(line):
            await buildlog(build_id, f"{line}\n")

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
            await build.parent.set_failed()
            await build.parent.logdone()
            session.commit()
            return False

        await build.set_needs_publish()
        session.commit()

        await build.set_publishing()
        await build.parent.set_publishing()
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

        done = True
        successful = True
        for sibling in build.parent.children:
            if sibling.buildstate == "building" or sibling.buildstate == "publishing":
                done = False
                break
            if sibling.buildstate != "successful":
                successful = False
        if done:
            if successful:
                await build.parent.set_successful()
            else:
                await build.parent.set_failed()

        session.commit()

        chroot = session.query(Chroot).filter(Chroot.id == chroot_id).first()
        chroot.ready = True
        chroot.basemirror.is_locked = True
        chroot.basemirror.mirror_state = "ready"

        session.commit()

        # Schedule builds
        args = {"schedule": []}
        await enqueue_task(args)

        return True


async def DeleteBuildEnv(dist, name, version, arch):
    """
    Delete sbuild chroot and other build environments.

    Args:
        dist (str): The distrelease
        version (str): The version
        arch (str): The architecture

    Returns:
        bool: True on success
    """

    logger.info("deleting build environments for %s-%s-%s", dist, version, arch)

    async def outh(line):
        pass

    process = Launchy(["sudo", "run-parts", "-a", "remove", "-a", dist, "-a", name,
                       "-a", version, "-a", arch,
                       "/etc/molior/mirror-hooks.d"], outh, outh)
    await process.launch()
    ret = await process.wait()

    if not ret == 0:
        logger.error("error deleting build env")
        return False

    return True
