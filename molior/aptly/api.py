import uuid
import json
import asyncio
import aiohttp

from ..app import logger
from ..molior.configuration import Configuration

from .taskstate import TaskState
from .errors import AptlyError


class AptlyApi:
    """Represents the aptly api.

    This class provides functions to interact
    with an aptly REST api server.
    """

    SUCCESS = range(200, 209)
    UNAUTHORIZED = [401, 403]
    INTERNAL_SERVER_ERROR = [500]
    NOT_FOUND = [404, 502]
    BAD_REQUEST = [400]

    # GPG passphrase file on aptly server machine
    PASSPHRASE_FILE = "/var/lib/aptly/gpg-pass"

    def __init__(self, api_url, gpg_key, username=None, password=None):
        self.url = api_url
        self.gpg_key = gpg_key
        if username:
            self.auth = aiohttp.BasicAuth(username, password=password)
        else:
            self.auth = None

    @staticmethod
    def __raise_aptly_error(response):
        """
        Raises an aptly error with
        the give response data.

        Raises:
            molior.aptly.errors.NotFoundError: If webserver returned 404.
            molior.aptly.errors.UnauthorizedError: If webserver returned 401.
        """
        raise AptlyError(response.text, "")

    def __check_status_code(self, status_code):
        """
        Checks the given status_code, raises
        exception if status_code does not mean
        successful.


        Args:
            status_code (int): The status_code to be checked.

        Returns:
            bool: True if status_code means success, otherwise False.
        """
        if status_code in self.SUCCESS:
            return True
        if status_code in self.NOT_FOUND:
            return False
        if status_code in self.UNAUTHORIZED:
            return False
        if status_code in self.BAD_REQUEST:
            return False

    @staticmethod
    def get_aptly_names(base_mirror, base_mirror_version, repo, version, is_mirror=False):
        """
        Returns the name and the publish_name
        of the given base_mirror, repo and version
        combination.

        Args:
            base_mirror (str): The basemirror name
            repo (str): The repo name
            version (str): The version
            is_mirror (bool: True if mirror otherwise False

        Returns:
            name: The aptly repository name
            publish_name: The aptly publish name
        """
        if is_mirror:
            tag = "mirrors"
        else:
            tag = "repos"

        if base_mirror:
            name = "{}-{}-{}-{}".format(base_mirror, base_mirror_version, repo, version)
            publish_name = "{}_{}_{}_{}_{}".format(base_mirror, base_mirror_version, tag, repo, version)
        else:
            name = "{}-{}".format(repo, version)
            publish_name = "{}_{}".format(repo, version)

        return name, publish_name

    def __prepare_content(self, data, headers=None):
        if data is not None:
            try:
                data = json.dumps(data)
                if headers is None:
                    headers = {"Content-Type": "application/json"}
                else:
                    headers.update({"Content-Type": "application/json"})
            except TypeError:  # not json, use default
                pass
        return data, headers

    async def GET(self, apipath, params=None):
        async with aiohttp.ClientSession() as http:
            async with http.get(self.url + apipath, auth=self.auth, params=params) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                return json.loads(await resp.text())

    async def POST(self, apipath, data=None):
        params = {"_async": "true"}
        data, headers = self.__prepare_content(data)
        async with aiohttp.ClientSession() as http:
            async with http.post(self.url + apipath, auth=self.auth, headers=headers, params=params, data=data) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                return json.loads(await resp.text())

    async def DELETE(self, apipath, headers=None, data=None):
        params = {"_async": "true"}
        data, headers = self.__prepare_content(data, headers)
        async with aiohttp.ClientSession() as http:
            async with http.delete(self.url + apipath, auth=self.auth, headers=headers, params=params, data=data) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                return json.loads(await resp.text())

    async def PUT(self, apipath, data=None):
        params = {"_async": "true"}
        data, headers = self.__prepare_content(data)
        async with aiohttp.ClientSession() as http:
            async with http.put(self.url + apipath, auth=self.auth, headers=headers, params=params, data=data) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                return json.loads(await resp.text())

    async def get_tasks(self):
        """
        Get aptly tasks.

        Returns:
            dict: task information

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        return await self.GET("/tasks")

    async def delete_task(self, task_id):
        """
        Deletes an aptly task by given task_id.

        Args:
            task_id(int): The task's id.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        return await self.DELETE(f"/tasks/{task_id}")

    async def get_task_state(self, task_id):
        """
        Get state of a aptly task.

        Returns:
            dict: state information

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        return await self.GET(f"/tasks/{task_id}")

    async def gpg_add_key(self, **kwargs):
        """
        Add gpg key from a key-server or key url.

        Kwargs:
            key_server (str): The key server's name.
            keys (list): The key for this server.
            key_url (str): The armored key url.

        Args:
            **kwargs: Arbitary keyword arguments.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        data = {"Keyring": "trustedkeys.gpg"}
        key_url = kwargs.get("key_url")
        keys = kwargs.get("keys", [])
        key_server = kwargs.get("key_server")

        if key_url:
            try:
                async with aiohttp.ClientSession() as http:
                    async with http.get(key_url) as resp:
                        if not resp.status == 200:
                            raise AptlyError("ConnectionError", "Could not download key")
                        data["GpgKeyArmor"] = await resp.text()
            except Exception:
                raise AptlyError("ConnectionError", "Could not download key: {}".format(key_url))
        else:
            data["Keyserver"] = key_server
            data["GpgKeyID"] = " ".join(keys)

        return await self.POST("/gpg/key", data=data)

    async def mirror_create(self, mirror, version, base_mirror, base_mirror_version, url, mirror_distribution,
                            components, architectures, mirror_filter, download_sources=True,
                            download_udebs=True, download_installer=True):
        """
        Creates a debian archive mirror.

        Args:
            FIXME: data (dict): Params for mirror creation.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        name, _ = self.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)

        for component in components:
            data = {
                "Name": "{}-{}".format(name, component),
                "ArchiveURL": url,
                "Distribution": mirror_distribution,
                "Components": [component],
                "Architectures": architectures,
                "DownloadSources": download_sources,
                "DownloadUdebs": download_udebs,
                "DownloadInstaller": download_installer,
                "Filter": mirror_filter,
                "FilterWithDeps": False,
            }

            if mirror_distribution == "./":
                data.pop("Components", None)
            await self.POST("/mirrors", data=data)

    async def mirror_update(self, base_mirror, base_mirror_version, mirror, version, components):
        """
        Creates a debian archive mirror.

        Args:
            mirror (str): The mirror's name.

        Returns:
            array of aptly task IDs

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        name, _ = self.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)

        tasks = []
        for component in components:
            data = {
                "Name": f"{name}-{component}",
                "ForceUpdate": True,
                "SkipExistingPackages": True,
                "MaxTries": 7,
            }

            task = await self.PUT(f"/mirrors/{name}-{component}", data=data)
            tasks.append(task["ID"])
        return tasks

    async def mirror_delete(self, base_mirror, base_mirror_version, mirror, version, mirror_distribution, components):
        """
        Delete a mirror from aptly and DB.

        Args:
            mirror (str): The mirror's name.
            version (str): The mirror's version.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        name, publish_name = self.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)

        # remove publish (may fail)
        try:
            task = await self.DELETE(f"/publish/{publish_name}/{mirror_distribution}")
            await self.wait_task(task["ID"])
        except Exception:
            logger.warning("Error deleting mirror publish  {}/{}".format(publish_name, mirror_distribution))

        # remove snapshots (may fail)
        try:
            await self.mirror_snapshot_delete(base_mirror, base_mirror_version, mirror, version, components)
        except Exception:
            logger.warning("Error deleting mirror snapshot {}/{}".format(publish_name, mirror_distribution))

        # remove mirrors
        for component in components:
            try:
                task = await self.DELETE(f"/mirrors/{name}-{component}")
                await self.wait_task(task["ID"])
            except Exception:
                logger.warning("Error deleting mirror {}/{}".format(publish_name, mirror_distribution))

        return True

    async def mirror_snapshot_delete(self, base_mirror, base_mirror_version, mirror, version, components):
        """
        Deletes a snapshot.

        Args:
            mirror (str): The mirror's name.
            version (str): The mirror's name.
            base_mirror (str): The mirror's base dist.
        """
        name, _ = self.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)

        for component in components:
            task = await self.DELETE(f"/snapshots/{name}-{component}")
            await self.wait_task(task["ID"])
        return True

    async def mirror_snapshot(self, base_mirror, base_mirror_version, mirror, version, components):
        """
        Creates a snapshot from a debian archive mirror.

        Args:
            mirror (str): Name of the mirror to get snapshotted.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """

        name, _ = self.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)
        tasks = []
        for component in components:
            data = {"Name": "{}-{}".format(name, component)}
            task = await self.POST(f"/mirrors/{name}-{component}/snapshots", data=data)
            tasks.append(task["ID"])
        return tasks

    async def mirror_get_progress(self, task_id):
        """
        Get progress of an actively running update on aptly.

        Returns:
            dict: Pending download information

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        progress = {}
        for i in range(20):
            try:
                state = await self.GET(f"/tasks/{task_id}")
                progress = await self.GET(f"/tasks/{task_id}/detail")
                break
            except Exception:
                logger.warning("Error fetching mirror progress, retrying in 30s")
                await asyncio.sleep(30)
                continue

        if not progress:
            progress = {
                "TotalNumberOfPackages": 0,
                "TotalDownloadSize": 0,
                "RemainingNumberOfPackages": 0,
                "RemainingDownloadSize": 0,
            }
        state.update(progress)
        return state

    async def mirror_publish(self, base_mirror, base_mirror_version, mirror, version,
                             mirror_distribution, components, architectures):
        """
        Publish a previously created snapshot from a debian archive mirror.

        Args:
            mirror (str): Name of the mirror-snapshot to get published.
            components (str): Name of components. (Only main accepted for now)

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        name, publish_name = self.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)
        data = {
            # Workaround for aptly ('/' not supported as mirror dist)
            "Distribution": mirror_distribution.replace("/", "_-"),
            "SourceKind": "snapshot",
            "Sources": [],
            "Architectures": architectures,
            "Signing": {
                "Batch": True,
                "GpgKey": self.gpg_key,
                "PassphraseFile": self.PASSPHRASE_FILE,
            },
            "AcquireByHash": True,
        }
        for component in components:
            data["Sources"].append({"Component": component, "Name": "{}-{}".format(name, component)})

        task = await self.POST(f"/publish/{publish_name}", data=data)
        return task["ID"]

    async def snapshot_create(self, repo_name, snapshot_name, package_refs=None):
        """
        Creates a complete snapshot of a repo or a snapshot with given package_refs.

        Args:
            name (str): Name of the snapshot.
            package_refs (list): Packages to create snapshot from.
                e.g. ["Pamd64 my-package 1.0.3 863efd9e94da9fbc"]
        """
        if package_refs:
            data = {"Name": snapshot_name, "PackageRefs": package_refs}
            task = await self.POST("/snapshots", data=data)
        else:
            data = {"Name": snapshot_name}
            task = await self.POST(f"/repos/{repo_name}/snapshots", data=data)
        return task["ID"]

    async def snapshot_delete(self, name):
        """
        Deletes a snapshot with the given name.

        Args:
            name (str): Name of the snapshot.

        Returns:
            int: Aptly's task id.
        """
        task = await self.DELETE(f"/snapshots/{name}")
        return task["ID"]

    async def snapshot_get(self):
        """
        Gets a list of all snapshots.

        Returns:
            list: List of snapshots
        """
        return await self.GET("/snapshots")

    async def snapshot_publish(self, name, component, archs, dist, destination):
        """
        Publishes a snapshot.

        Args:
            name (str): Name of the snapshot to be published.
            component (str): Component to be published.
            archs (list): Archs to be published.
            dist (str): Distribution to be published.
            destination (str): Publish point destination name.
                e.g. jessie_8.8_repos_test_1
        """
        if not archs:
            logger.error("snapshot_publish: emtpy architectures")

        data = {
            "SourceKind": "snapshot",
            "Sources": [{"Name": name, "Component": component}],
            "Architectures": archs,
            "Distribution": dist,
            "Signing": {
                "Batch": True,
                "GpgKey": self.gpg_key,
                "PassphraseFile": self.PASSPHRASE_FILE,
            },
            "AcquireByHash": True,
        }

        task = await self.POST(f"/publish/{destination}", data=data)
        return task["ID"]

    async def snapshot_publish_update(self, name, component, dist, destination):
        """
        Publishes a snapshot.

        Args:
            name (str): Name of the snapshot to be published.
            component (str): Component to be published.
            dist (str): Distribution to be published.
            destination (str): Publish point destination name.
                e.g. jessie_8.8_repos_test_1
        """
        data = {
            "Snapshots": [{"Name": name, "Component": component}],
            "Signing": {
                "Batch": True,
                "GpgKey": self.gpg_key,
                "PassphraseFile": self.PASSPHRASE_FILE,
            },
            "AcquireByHash": True,
        }

        task = await self.PUT(f"/publish/{destination}/{dist}", data=data)
        return task["ID"]

    async def snapshot_rename(self, name, new_name):
        """
        Rename a snapshot

        Args:
            name (str): Original name
            new_name (str): New name
        """
        data = {"Name": new_name}
        task = await self.PUT(f"/snapshots/{name}", data=data)
        return task["ID"]

    async def repo_packages_get(self, repo_name, search=None):
        """
        Gets a list of all packages from a local repository.

        Args:
            repo_name (str): The repository's name.
                e.g. jessie-8.8-test-1

        Returns:
            list: List of package refs.
        """
        params = None
        if search:
            params = {"q": search}
        return await self.GET(f"/repos/{repo_name}/packages", params=params)

    async def repo_packages_delete(self, repo_name, package_refs):
        """
        Removes given packages from the given repository.

        Args:
            repo_name (str): The repository's name.
            package_refs (list): Packages to be removed.
        """
        data = {"PackageRefs": package_refs}
        headers = {"content-type": "application/json"}
        task = await self.DELETE(f"/repos/{repo_name}/packages", headers=headers, data=data)
        return task["ID"]

    async def repo_get(self):
        """
        Gets a list of all repositories.

        Returns:
            list: List of repos.
        """
        return await self.GET("/repos")

    async def repo_add(self, repo_name, files):
        """
        Adds the given files to a local aptly repository.

        Args:
            repo_name (str): The repository's name.
            files (list): List of file_paths to be added.

        Returns:
            int: The aptly task's id.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        # FIXME: use secret
        upload_dir = str(uuid.uuid4())
        for filename in files:
            try:
                with open(filename, "rb") as _file:
                    post_files = {"file": _file}
                    await self.POST(f"/files/{upload_dir}", data=post_files)
            except Exception as exc:
                logger.exception(exc)

        task = await self.POST(f"/repos/{repo_name}/file/{upload_dir}")
        return task["ID"], upload_dir

    async def repo_create(self, name):
        """
        Creates an aptly repository.

        Args:
            name (str): The repository's name.

        Returns:
            bool: True if creation was successful, otherwise False.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        data = {"Name": name}
        return await self.POST("/repos", data=data)

    async def repo_delete(self, name):
        """
        Deletes an aptly repository.

        Args:
            name (str): The repository's name.

        Returns:
            bool: True if creation was successful, otherwise False.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        task = await self.DELETE(f"/repos/{name}")
        return task["ID"]

    async def repo_rename(self, name, new_name):
        """
        Rename an aptly repository.

        Args:
            name (str): The repository's name.

        Returns:
            bool: True if creation was successful, otherwise False.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        data = {"Name": new_name}
        task = await self.PUT(f"/repos/{name}", data=data)
        return task

    async def delete_directory(self, directory_name):
        """
        Deletes the given directory on the aptly server.

        Args:
            directory_name (str): The directory's name.
        """
        return await self.DELETE(f"/files/{directory_name}")

    async def publish_get(self):
        """
        Gets a list of all publish points.

        Returns:
            list: List of publish points
        """
        return await self.GET("/publish")

    async def publish_drop(self, base_mirror, base_mirror_version, repo, version, distribution):
        """
        Deletes a publish point.

        Args:
            base_mirror (str): Name of the basemirror in format 'distribution-version' (e.g. 'jessie-8.10').
            repo (str): Name of the repository
            version (str): Name of the repository version
            distribution (str): The publish point dist.

        Returns:
            list: List of publish points
        """
        _, publish_name = self.get_aptly_names(base_mirror, base_mirror_version, repo, version)
        task = await self.DELETE(f"/publish/{publish_name}/{distribution}")
        return task["ID"]

    async def cleanup(self):
        """
        Aptly DB Cleanup

        Args:

        Returns:
        """
        task = await self.POST("/db/cleanup")

        task_id = task.get("ID")
        if task_id:
            if not await self.wait_task(task_id):
                logger.error("aptly: cleanup task failed")
                return False
        logger.info("aptly: cleanup succeeded")
        return True

    async def republish(self, dist, repo_name, publish_name):
        snapshot_name_tmp = get_snapshot_name(publish_name, dist, temporary=True)

        # package_refs = await self.__get_packages(ci_build)
        # logger.warning("creating snapshot with name '%s' and the packages: '%s'", snapshot_name_tmp, str(package_refs))

        try:
            snapshots = await self.GET("/snapshots")
            for snapshot in snapshots:
                if snapshot["Name"] == snapshot_name_tmp:
                    # delete leftover tmp snapshot
                    logger.warning("deleting existing tmp snapshot")
                    try:
                        task_id = await self.snapshot_delete(snapshot_name_tmp)
                        await self.wait_task(task_id)
                    except Exception as exc:
                        logger.error(f"Error deleting existing tmp snapshot: {snapshot_name_tmp}")
                        logger.exception(exc)
                    break
        except Exception as exc:
            logger.error("Error loading snapshots")
            logger.exception(exc)

        task_id = await self.snapshot_create(repo_name, snapshot_name_tmp)
        if not await self.wait_task(task_id):
            return False

        logger.debug("switching published snapshot at '%s' dist '%s' with new created snapshot '%s'",
                     publish_name,
                     dist,
                     snapshot_name_tmp)

        task_id = await self.snapshot_publish_update(snapshot_name_tmp, "main", dist, publish_name)
        if not await self.wait_task(task_id):
            return False

        snapshot_name = get_snapshot_name(publish_name, dist, temporary=False)
        try:
            task_id = await self.snapshot_delete(snapshot_name)
            await self.wait_task(task_id)
        except Exception:
            pass

        task_id = await self.snapshot_rename(snapshot_name_tmp, snapshot_name)
        if not await self.wait_task(task_id):
            return False

        return True

    async def wait_task(self, task_id):
        """
        Waits for an aptly task to finish.

        Args:
            task_id(int): The task's id.

        Returns:
            bool: True if task was succesful, otherwise False.
        """
        if type(task_id) is not int:
            raise Exception("task_id '%s' must be int" % str(task_id))

        while True:
            await asyncio.sleep(2)
            try:
                task_state = await self.get_task_state(task_id)
            except Exception as exc:
                logger.exception(exc)
                return False

            if task_state.get("State") == TaskState.SUCCESSFUL.value:
                await self.delete_task(task_id)
                return True

            if task_state.get("State") == TaskState.FAILED.value:
                output = await self.GET(f"/tasks/{task_id}/output")
                logger.error(f"aptly task failed: {output}")
                await self.delete_task(task_id)
                return False

    async def version(self):
        """
        Gets aptly version.

        Returns:
            string: version
        """
        version = "unknown"
        async with aiohttp.ClientSession() as http:
            async with http.get(self.url + "/version", auth=self.auth) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
                version = data.get("Version", "unknown")
        return version


def get_aptly_connection():
    """
    Connects to aptly server and returns aptly
    object.

    Returns:
        AptlyApi: The connected aptly api instance.
    """
    cfg = Configuration()
    api_url = cfg.aptly.get("api_url")
    gpg_key = cfg.aptly.get("gpg_key")
    aptly_user = cfg.aptly.get("user")
    aptly_passwd = cfg.aptly.get("pass")
    aptly = AptlyApi(api_url, gpg_key, username=aptly_user, password=aptly_passwd)
    return aptly


def get_snapshot_name(publish_name, dist, temporary=False):
    """
        Returns a aptly snapshot name

        Args:
            dist (str): The distribution to be used (stable, unstable)
            temporary (bool): use tempporary extension
    """
    return "{}-{}{}".format(publish_name, dist, "-tmp" if temporary else "")
