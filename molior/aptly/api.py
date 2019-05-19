"""
This module provides the aptly REST
api wrapper class.
"""
import uuid
import json
import asyncio
import aiohttp

from molior.aptly.errors import AptlyError
from .taskstate import TaskState


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
        self.__api_url = api_url
        self.gpg_key = gpg_key
        self.headers = {"content-type": "application/json"}
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

    async def get_tasks(self):
        """
        Get aptly tasks.

        Returns:
            dict: task information

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        tasks = []
        async with aiohttp.ClientSession() as http:
            async with http.get(self.__api_url + "/tasks", auth=self.auth) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                tasks = json.loads(await resp.text())
        return tasks

    async def delete_task(self, task_id):
        """
        Deletes an aptly task by given task_id.

        Args:
            task_id(int): The task's id.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        async with aiohttp.ClientSession() as http:
            async with http.delete(
                self.__api_url + "/tasks/{}".format(task_id), auth=self.auth
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)

    async def get_task_state(self, task_id):
        """
        Get state of a aptly task.

        Returns:
            dict: state information

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        state = []
        async with aiohttp.ClientSession() as http:
            async with http.get(
                self.__api_url + "/tasks/{}".format(task_id), auth=self.auth
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                state = json.loads(await resp.text())
        return state

    async def wait_task(self, task_id):
        """
        Waits for an aptly task to finish.

        Args:
            task_id(int): The task's id.

        Returns:
            bool: True if task was succesful, otherwise False.
        """
        while True:
            try:
                task_state = await self.get_task_state(task_id)
            except Exception:
                return False

            if task_state.get("State") == TaskState.SUCCESSFUL.value:
                await self.delete_task(task_id)
                return True
            if task_state.get("State") == TaskState.FAILED.value:
                await self.delete_task(task_id)
                return False

            await asyncio.sleep(2)

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
                            raise AptlyError(
                                "ConnectionError", "Could not download key"
                            )
                        data["GpgKeyArmor"] = await resp.text()
            except Exception:
                raise AptlyError(
                    "ConnectionError", "Could not download key: {}".format(key_url)
                )

            async with aiohttp.ClientSession() as http:
                async with http.post(
                    self.__api_url + "/gpg/key",
                    headers=self.headers,
                    data=json.dumps(data),
                    auth=self.auth,
                ) as resp:
                    if not self.__check_status_code(resp.status):
                        self.__raise_aptly_error(resp)
        else:
            data["Keyserver"] = key_server
            for key in keys:
                data["GpgKeyID"] = key
                async with aiohttp.ClientSession() as http:
                    async with http.post(
                        self.__api_url + "/gpg/key",
                        headers=self.headers,
                        data=json.dumps(data),
                        auth=self.auth,
                    ) as resp:
                        if not self.__check_status_code(resp.status):
                            self.__raise_aptly_error(resp)

    async def mirror_create(
        self,
        mirror,
        version,
        base_mirror,
        base_mirror_version,
        url,
        mirror_distribution,
        components,
        architectures,
        download_sources=True,
        download_udebs=True,
        download_installer=True,
    ):
        """
        Creates a debian archive mirror.

        Args:
            FIXME: data (dict): Params for mirror creation.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        name, _ = self.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)

        data = {
            "Name": name,
            "ArchiveURL": url,
            "Distribution": mirror_distribution,
            "Components": components,
            "Architectures": architectures,
            "DownloadSources": download_sources,
            "DownloadUdebs": download_udebs,
            "DownloadInstaller": download_installer,
        }

        async with aiohttp.ClientSession() as http:
            async with http.post(
                self.__api_url + "/mirrors",
                headers=self.headers,
                data=json.dumps(data),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)

    async def mirror_update(self, base_mirror, base_mirror_version, mirror, version):
        """
        Creates a debian archive mirror.

        Args:
            mirror (str): The mirror's name.

        Returns:
            aptly task ID

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """
        name, _ = self.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)

        data = {
            "Name": name,
            "ForceUpdate": True,
            "SkipExistingPackages": True,
            "MaxTries": 7,
        }

        async with aiohttp.ClientSession() as http:
            async with http.put(
                self.__api_url + "/mirrors/{}".format(name),
                headers=self.headers,
                data=json.dumps(data),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                res = json.loads(await resp.text())
        return res["ID"]

    async def mirror_delete(self, base_mirror, base_mirror_version, mirror, version, mirror_distribution):
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

        try:
            # remove publish (may fail)
            async with aiohttp.ClientSession() as http:
                async with http.delete(
                    self.__api_url
                    + "/publish/{}/{}".format(publish_name, mirror_distribution),
                    auth=self.auth,
                ) as resp:
                    if self.__check_status_code(resp.status):
                        data = json.loads(await resp.text())
                        await self.wait_task(data["ID"])

            # remove snapshot (may fail)
            await self.mirror_snapshot_delete(base_mirror, mirror, version)
        except Exception:
            # FIXME: log warning? logger.exception(exc)
            pass

        async with aiohttp.ClientSession() as http:
            async with http.delete(
                self.__api_url + "/mirrors/{}".format(name), auth=self.auth
            ) as resp:
                if self.__check_status_code(resp.status):
                    data = json.loads(await resp.text())
                    return await self.wait_task(data["ID"])
        return False

    async def mirror_snapshot_delete(self, base_mirror, base_mirror_version, mirror, version):
        """
        Deletes a snapshot.

        Args:
            mirror (str): The mirror's name.
            version (str): The mirror's name.
            base_mirror (str): The mirror's base dist.
        """
        name, _ = self.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)

        async with aiohttp.ClientSession() as http:
            async with http.delete(
                self.__api_url + "/snapshots/{}".format(name), auth=self.auth
            ) as resp:
                if self.__check_status_code(resp.status):
                    data = json.loads(await resp.text())
                    return await self.wait_task(data["ID"])
        return False

    async def mirror_snapshot(self, base_mirror, base_mirror_version, mirror, version):
        """
        Creates a snapshot from a debian archive mirror.

        Args:
            mirror (str): Name of the mirror to get snapshotted.

        Raises:
            molior.aptly.errors.AptlyError: If a known error occurs while
                communicating with the aptly api.
        """

        name, _ = self.get_aptly_names(base_mirror, base_mirror_version, mirror, version, is_mirror=True)
        data = {"Name": name}

        async with aiohttp.ClientSession() as http:
            async with http.post(
                self.__api_url + "/mirrors/{}/snapshots".format(name),
                headers=self.headers,
                data=json.dumps(data),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                res = json.loads(await resp.text())
        return res["ID"]

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
        async with aiohttp.ClientSession() as http:
            async with http.get(
                self.__api_url + "/tasks/{}".format(task_id), auth=self.auth
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                state = json.loads(await resp.text())

            async with http.get(
                self.__api_url + "/tasks/{}/detail".format(task_id), auth=self.auth
            ) as resp:
                if self.__check_status_code(resp.status):
                    progress = json.loads(await resp.text())

        if not progress:
            progress = {
                "TotalNumberOfPackages": 0,
                "TotalDownloadSize": 0,
                "RemainingNumberOfPackages": 0,
                "RemainingDownloadSize": 0,
            }
        state.update(progress)

        if state["TotalNumberOfPackages"] > 0:
            state["PercentPackages"] = (
                (state["TotalNumberOfPackages"] - state["RemainingNumberOfPackages"])
                / state["TotalNumberOfPackages"]
                * 100.0
            )
        else:
            state["PercentPackages"] = 0.0

        if "TotalDownloadSize" in state and state["TotalDownloadSize"] > 0:
            state["PercentSize"] = (
                (state["TotalDownloadSize"] - state["RemainingDownloadSize"])
                / state["TotalDownloadSize"]
                * 100.0
            )
        else:
            state["PercentSize"] = 0.0

        return state

    async def mirror_publish(self, base_mirror, base_mirror_version, mirror, version, mirror_distribution, components):
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
            "Distribution": mirror_distribution,
            "SourceKind": "snapshot",
            "Sources": [],
            "Signing": {
                "Batch": True,
                "GpgKey": self.gpg_key,
                "PassphraseFile": self.PASSPHRASE_FILE,
            },
            "AcquireByHash": True,
        }
        for component in components:
            data["Sources"].append({"Component": component, "Name": name})

        async with aiohttp.ClientSession() as http:
            async with http.post(
                self.__api_url + "/publish/{}".format(publish_name),
                headers=self.headers,
                data=json.dumps(data),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
        return data["ID"]

    async def snapshot_create(self, name, package_refs):
        """
        Creates a snapshot with given package_refs.

        Args:
            name (str): Name of the snapshot.
            package_refs (list): Packages to create snapshot from.
                e.g. ["Pamd64 my-package 1.0.3 863efd9e94da9fbc"]
        """
        data = {"Name": name, "PackageRefs": package_refs}
        async with aiohttp.ClientSession() as http:
            async with http.post(
                self.__api_url + "/snapshots",
                headers=self.headers,
                data=json.dumps(data),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
        return data["ID"]

    async def snapshot_delete(self, name):
        """
        Deletes a snapshot with the given name.

        Args:
            name (str): Name of the snapshot.

        Returns:
            int: Aptly's task id.
        """
        data = {"force": "1"}
        async with aiohttp.ClientSession() as http:
            async with http.delete(
                self.__api_url + "/snapshots/{}".format(name),
                headers=self.headers,
                data=json.dumps(data),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
        return data["ID"]

    async def snapshot_get(self):
        """
        Gets a list of all snapshots.

        Returns:
            list: List of snapshots
        """
        data = None
        async with aiohttp.ClientSession() as http:
            async with http.get(self.__api_url + "/snapshots", auth=self.auth) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
        return data

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

        async with aiohttp.ClientSession() as http:
            async with http.post(
                self.__api_url + "/publish/{}".format(destination),
                headers=self.headers,
                data=json.dumps(data),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
        return data["ID"]

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

        async with aiohttp.ClientSession() as http:
            async with http.put(
                self.__api_url + "/publish/{}/{}".format(destination, dist),
                headers=self.headers,
                data=json.dumps(data),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
        return data["ID"]

    async def repo_packages_get(self, repo_name):
        """
        Gets a list of all packages from a local repository.

        Args:
            repo_name (str): The repository's name.
                e.g. jessie-8.8-test-1

        Returns:
            list: List of package refs.
        """
        data = None
        async with aiohttp.ClientSession() as http:
            async with http.get(
                self.__api_url + "/repos/{}/packages".format(repo_name), auth=self.auth
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
        return data

    async def repo_packages_delete(self, repo_name, package_refs):
        """
        Removes given packages from the given repository.

        Args:
            repo_name (str): The repository's name.
            package_refs (list): Packages to be removed.
        """
        data = {"PackageRefs": package_refs}
        async with aiohttp.ClientSession() as http:
            async with http.delete(
                self.__api_url + "/repos/{}/packages".format(repo_name),
                data=json.dumps(data),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
        return data["ID"]

    async def repo_get(self):
        """
        Gets a list of all repositories.

        Returns:
            list: List of repos.
        """
        data = None
        async with aiohttp.ClientSession() as http:
            async with http.get(self.__api_url + "/repos", auth=self.auth) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
        return data

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
        upload_dir = str(uuid.uuid4())
        for filename in files:
            with open(filename, "rb") as _file:
                post_files = {"file": _file}
                async with aiohttp.ClientSession() as http:
                    async with http.post(
                        self.__api_url + "/files/{}".format(upload_dir),
                        auth=self.auth,
                        data=post_files,
                    ) as resp:
                        if not self.__check_status_code(resp.status):
                            self.__raise_aptly_error(resp)

        async with aiohttp.ClientSession() as http:
            async with http.post(
                self.__api_url + "/repos/{}/file/{}".format(repo_name, upload_dir),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())

        return data.get("ID"), upload_dir

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
        async with aiohttp.ClientSession() as http:
            async with http.post(
                self.__api_url + "/repos",
                headers=self.headers,
                data=json.dumps(data),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
        return True

    async def delete_directory(self, directory_name):
        """
        Deletes the given directory on the aptly server.

        Args:
            directory_name (str): The directory's name.
        """
        async with aiohttp.ClientSession() as http:
            async with http.delete(
                self.__api_url + "/files/{}".format(directory_name), auth=self.auth
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
        return True

    async def publish_get(self):
        """
        Gets a list of all publish points.

        Returns:
            list: List of publish points
        """
        data = None
        async with aiohttp.ClientSession() as http:
            async with http.get(self.__api_url + "/publish", auth=self.auth) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
                data = json.loads(await resp.text())
        return data

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
        async with aiohttp.ClientSession() as http:
            async with http.delete(
                self.__api_url + "/publish/{}/{}".format(publish_name, distribution),
                auth=self.auth,
            ) as resp:
                if not self.__check_status_code(resp.status):
                    self.__raise_aptly_error(resp)
        return True
