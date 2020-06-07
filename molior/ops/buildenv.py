from launchy import Launchy

from ..app import logger
from ..tools import write_log, write_log_title
from ..model.database import Session
from ..model.build import Build


async def CreateBuildEnv(task_queue, chroot_id, build_id, dist, name, version, arch, components):
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

        await write_log_title(build_id, "Chroot Environment")

        await build.set_building()
        session.commit()

        logger.info("creating build environments for %s-%s-%s", dist, version, arch)
        await write_log(build_id, "Creating build environments for %s-%s-%s\n\n" % (dist, version, arch))

        async def outh(line):
            await write_log(build_id, "%s\n" % line)

        process = Launchy(["sudo", "run-parts", "-a", "build", "-a", dist, "-a", name,
                           "-a", version, "-a", arch, "-a", components,
                           "/etc/molior/mirror-hooks.d"], outh, outh)
        await process.launch()
        ret = await process.wait()

        if not ret == 0:
            logger.error("error creating build env")
            await write_log(build_id, "Error creating build environment\n")
            await write_log(build_id, "\n")
            await write_log_title(build_id, "Done", no_footer_newline=True)
            await build.set_failed()
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
            await write_log(build_id, "Error publishing build environment\n")
            await write_log_title(build_id, "Done", no_footer_newline=True)
            await build.set_publish_failed()
            session.commit()
            return False

        await write_log(build_id, "\n")
        await write_log_title(build_id, "Done", no_footer_newline=True)
        await build.set_successful()
        session.commit()

        chroot = session.query(Chroot).filter(Chroot.id == chroot_id).first()
        chroot.ready = True
        session.commit()

        # Schedule builds
        args = {"schedule": []}
        await task_queue.put(args)

        return True
