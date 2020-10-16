import asyncio

from datetime import datetime, timedelta

from ..app import logger
from ..tools import get_aptly_connection
from ..aptly import TaskState
from .configuration import Configuration


class DebianRepository:
    """
    Represents a remote debian repository.
    """

    DISTS = ["stable", "unstable"]
    # Time to live for ci packages in days
    CI_PACKAGES_TTL = 7
    DATETIME_FORMAT = "%Y%m%d%H%M%S"

    def __init__(self, basemirror_name, basemirror_version, project_name, project_version, archs):
        self.basemirror_name = basemirror_name
        self.basemirror_version = basemirror_version
        self.project_name = project_name
        self.project_version = project_version
        self.archs = archs

        self.__api = get_aptly_connection()
        ci_cfg = Configuration().ci_builds
        ci_ttl = ci_cfg.get("packages_ttl") if ci_cfg else None
        self.__ci_packages_ttl = ci_ttl if ci_ttl else self.CI_PACKAGES_TTL

    @property
    def publish_name(self):
        """
        Returns the publish name/string of the
        debian repository.

        Examples:
            jessie_8.8_repos_test_1
            stretch_9.2_repos_test_2
        """

        return "{}_{}_repos_{}_{}".format(self.basemirror_name, self.basemirror_version, self.project_name, self.project_version)

    @property
    def name(self):
        """
        Returns the name of the debian repository.

        Examples:
            jessie-8.8-test-1
            stretch-9.2-test-2
        """
        return "{}-{}-{}-{}".format(self.basemirror_name, self.basemirror_version, self.project_name, self.project_version)

    async def init(self):
        """
        Creates stable and unstable snapshots and publish points
        if they don't already exist.
        """
        logger.debug("init repository called for '%s'", self.name)
        snapshots = await self.__api.snapshot_get()
        repos = await self.__api.repo_get()

        for dist in self.DISTS:
            repo_name = self.name + "-%s" % dist
            for repo in repos:
                if repo.get("Name") == repo_name:
                    logger.error("repository '%s' already exists", repo_name)
                    return False
            snapshot_name = self.__get_snapshot_name(dist)
            for snapshot in snapshots:
                if snapshot.get("Name") == snapshot_name:
                    logger.error("publish point for '%s' already exists", snapshot_name)
                    return False

        for dist in self.DISTS:
            repo_name = self.name + "-%s" % dist
            logger.info("creating repository '%s'", repo_name)
            await self.__api.repo_create(repo_name)  # not a background task

            snapshot_name = self.__get_snapshot_name(dist)

            logger.debug("creating empty snapshot: '%s'", snapshot_name)

            # package_refs = await self.__get_packages(dist == "unstable")
            task_id = await self.__api.snapshot_create(repo_name, snapshot_name)
            await self.__await_task(task_id)

            # Add source and all archs per default
            archs = self.archs + ["source", "all"]

            logger.debug("publishing snapshot: '%s' archs: '%s'", snapshot_name, str(archs))
            task_id = await self.__api.snapshot_publish(snapshot_name, "main", archs, dist, self.publish_name)
            await self.__await_task(task_id)
        return True

    async def snapshot(self, snapshot_version, packages):
        """
        Create a snapshot of a reporitory with latest builds.
        """
        dist = "stable"
        repo_name = self.name + "-%s" % dist

        publish_name = "{}_{}_repos_{}_{}".format(self.basemirror_name, self.basemirror_version,
                                                  self.project_name, snapshot_version)
        snapshot_name = "{}-{}".format(publish_name, dist)

        logger.info("creating release snapshot: '%s'", snapshot_name)

        package_refs = []
        for package in packages:
            pkgs = await self.__api.repo_packages_get(repo_name, "%s (= %s) {%s}" % (package[0],
                                                                                     package[1],
                                                                                     package[2]))
            package_refs += pkgs

        logger.info("snapshot: pkg refs %s" % package_refs)
        task_id = await self.__api.snapshot_create(repo_name, snapshot_name, package_refs)
        await self.__await_task(task_id)

        task_id = await self.__api.snapshot_publish(snapshot_name, "main", self.archs, dist, publish_name)
        await self.__await_task(task_id)
        return True

    async def delete(self):
        """
        Delete a repository including publish point amd snapshots
        """
        for dist in self.DISTS:
            repo_name = self.name + "-%s" % dist
            try:
                # FIXME: should this aptly task run in background?
                await self.__api.publish_drop(self.basemirror_name,
                                              self.basemirror_version,
                                              self.project_name,
                                              self.project_version, dist)
            except Exception as exc:
                logger.warning("Error deleting publish point of repo '%s'" % repo_name)
                logger.exception(exc)

            # FIXME: delete also old timestamped snapshots
            snapshot_name = self.__get_snapshot_name(dist)
            try:
                task_id = await self.__api.snapshot_delete(snapshot_name)
                await self.__await_task(task_id)
            except Exception as exc:
                logger.warning("Error deleting snapshot '%s'" % snapshot_name)
                logger.exception(exc)
            try:
                # FIXME: should this aptly task run in background?
                await self.__api.repo_delete(repo_name)
            except Exception as exc:
                logger.warning("Error deleting repo '%s'" % repo_name)
                logger.exception(exc)

    def __get_snapshot_name(self, dist, temporary=False):
        """
            Generates a snapshot name for the repository.

            Args:
                dist (str): The distribution to be used.
                    e.g. stable, unstable
                without_timestamp (bool): Excludes timestamp if True.
        """
        return "{}-{}{}".format(self.publish_name, dist, "-tmp" if temporary else "")

    async def __await_task(self, task_id):
        if type(task_id) is not int:
            raise Exception("task_id '%s' must be int" % str(task_id))

        while True:
            try:
                task_state = await self.__api.get_task_state(task_id)
            except Exception as exc:
                logger.exception(exc)
                return False

            if task_state.get("State") == TaskState.SUCCESSFUL.value:
                await self.__api.delete_task(task_id)
                return True

            if task_state.get("State") == TaskState.FAILED.value:
                await self.__api.delete_task(task_id)
                return False

            await asyncio.sleep(2)

    async def __remove_old_packages(self, packages):
        """
        Removes all packages that are older than <today> - <timetolive>
        from the debian repo.

        Args:
            packages (list): List of package refs.
                e.g. ['Pi386 hooks-test 1.0.3+git20171128085843-57121d3 c36ac']

        Returns:
            list: List of packages.
        """
        now = datetime.now()
        delete_date = now - timedelta(days=self.__ci_packages_ttl)

        old_packages = []
        for pkg in packages:
            if "+git" not in pkg:
                continue
            gitpart = pkg.split("+git")[1]
            if "-" in gitpart:
                dt_str = gitpart.split("-")[0]
            else:
                dt_str = gitpart.split(".")[0]
            timestamp = datetime.strptime(dt_str, self.DATETIME_FORMAT)
            if timestamp < delete_date:
                old_packages.append(pkg)

        if not old_packages:
            return packages

        repo_name = self.name + "-unstable"
        try:
            for old_package in old_packages[:1]:
                logger.info("removing old package from aptly: '%s'", old_package)
                task_id = await self.__api.repo_packages_delete(repo_name, [old_package])
                ret = await self.__await_task(task_id)
                if not ret:
                    logger.error("Error deleting package: %s (task %d)", old_package, task_id)
        except Exception as exc:
            logger.exception(exc)

        return list(set(packages) - set(old_packages))

    async def add_packages(self, files, ci_build=False):
        """
        Adds the given files/packages to the debian repository,
        creates a new snapshot and publishes the snapshot.

        Args:
            files (list): List of filepaths to the package files.
            ci_build (bool): Packages will be pushed to the unstable
                publish point if set to True.
        """
        dist = "unstable" if ci_build else "stable"
        repo_name = self.name + "-%s" % dist
        task_id, upload_dir = await self.__api.repo_add(repo_name, files)

        logger.debug("repo add returned aptly task id '%s' and upload dir '%s'", task_id, upload_dir)
        logger.debug("waiting for repo add task with id '%s' to finish", task_id)

        await self.__await_task(task_id)

        logger.debug("repo add task with id '%s' has finished", task_id)
        logger.debug("deleting temporary upload dir: '%s'", upload_dir)

        await self.__api.delete_directory(upload_dir)

        snapshot_name_tmp = self.__get_snapshot_name(dist, temporary=True)

        # package_refs = await self.__get_packages(ci_build)
        # logger.warning("creating snapshot with name '%s' and the packages: '%s'", snapshot_name_tmp, str(package_refs))

        task_id = await self.__api.snapshot_create(repo_name, snapshot_name_tmp)
        await self.__await_task(task_id)

        logger.debug("switching published snapshot at '%s' dist '%s' with new created snapshot '%s'",
                     self.publish_name,
                     dist,
                     snapshot_name_tmp)

        task_id = await self.__api.snapshot_publish_update(snapshot_name_tmp, "main", dist, self.publish_name)
        await self.__await_task(task_id)

        snapshot_name = self.__get_snapshot_name(dist, temporary=False)
        try:
            task_id = await self.__api.snapshot_delete(snapshot_name)
            await self.__await_task(task_id)
        except Exception:
            pass
        task_id = await self.__api.snapshot_rename(snapshot_name_tmp, snapshot_name)
        await self.__await_task(task_id)
