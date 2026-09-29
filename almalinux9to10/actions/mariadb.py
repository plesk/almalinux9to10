# Copyright 1999 - 2026. WebPros International GmbH. All rights reserved.

import os
import re
import subprocess
import typing
from functools import partial

from pleskdistup.common import action, leapp_configs, files, log, mariadb, rpm
from pleskdistup.actions.packages import RemoveReplacePackages
from .common import get_adapted_repository


# The MariaDB version shipped by the source OS (AlmaLinux 9 base AppStream).
# Anything newer is assumed to come from a vendor repository and has to be
# remapped for the target OS explicitly.
MARIADB_VERSION_ON_ALMA = mariadb.MariaDBVersion("10.5.29")
KNOWN_MARIADB_REPO_FILES = [
    "mariadb.repo",
    "mariadb10.repo",
    "cl-mysql.repo"
]
MARIADB_PACKMAP: typing.Dict[str, str] = {
    "MariaDB-client": '',
    "MariaDB-client-compat": '',
    "MariaDB-compat": '',
    "MariaDB-common": '',
    "MariaDB-server": '',
    "MariaDB-server-compat": '',
    "MariaDB-shared:": ''
}


def _find_mariadb_repo_files() -> typing.List[str]:
    return files.find_files_case_insensitive("/etc/yum.repos.d", KNOWN_MARIADB_REPO_FILES)


def _is_governor_mariadb_installed() -> bool:
    if not mariadb.is_mariadb_installed() and not mariadb.is_mysql_installed():
        return False

    repofiles = _find_mariadb_repo_files()
    for repofile in repofiles:
        for repo in rpm.extract_repodata(repofile):
            if repo.url and "repo.almalinux.com" in repo.url and ("cl-mariadb" in repo.url or "cl-mysql" in repo.url):
                return True

    return False


class AssertMariadbRepoAvailable(action.CheckAction):
    def __init__(self) -> None:
        self.name = "check mariadb repo available"
        self.description = """
The MariaDB repository with id '{}' from the file '{}' is not accessible.
\tThis issue may be caused by the deprecation of the currently installed MariaDB version or the disabling
\tof the MariaDB repository by the provider. To resolve this, update MariaDB to any version from the official
\trepository 'rpm.mariadb.org', or use the official archive repository for your current MariaDB version at 'archive.mariadb.org'.
"""

    def _do_check(self) -> bool:
        if not mariadb.is_mariadb_installed() or not mariadb.get_installed_mariadb_version() > MARIADB_VERSION_ON_ALMA:
            return True

        repofiles = _find_mariadb_repo_files()
        if len(repofiles) == 0:
            return True

        for repofile in repofiles:
            for repo in rpm.extract_repodata(repofile):
                if not repo.url or ".mariadb.org" not in repo.url:
                    continue

                # Since repository will be deprecated for any distro at once it looks fine to check only for 9 on x86_64
                repo_baseurl = repo.url.replace("$releasever", "9").replace("$basearch", "x86_64")
                result = subprocess.run(["curl", "-s", "-o", "/dev/null", "-f", repo_baseurl])
                if result.returncode != 0:
                    self.description = self.description.format(repo.id, repofile)
                    return False

        return True


class UpdateModernMariadb(RemoveReplacePackages):
    def __init__(self) -> None:
        super().__init__(
            {"perl-DBD-MySQL": "perl-DBD-MariaDB"},
            "/usr/local/psa/var/almalinux9to10/dist-upgrader-mariadb.list",
            "update modern MariaDB")

    def _is_required(self) -> bool:
        return (
            mariadb.is_mariadb_installed()
            and mariadb.get_installed_mariadb_version() > MARIADB_VERSION_ON_ALMA
            and not _is_governor_mariadb_installed()
        )

    def _prepare_action(self) -> action.ActionResult:
        repofiles = _find_mariadb_repo_files()
        if len(repofiles) == 0:
            raise Exception("Mariadb installed from unknown repository."
                            "Please check the '{}' file is present".format(
                                "/etc/yum.repos.d/mariadb.repo"))

        log.debug("Add MariaDB repository files '{}' mapping into leapp vendor directory".format(repofiles[0]))
        for repofile in repofiles:
            leapp_configs.create_leapp_vendor_repository_adoption(
                repofile,
                do_adapt_repository=partial(get_adapted_repository, keep_id=False),
                distro="almalinux", source_major_version="9", target_major_version="10",
            )

        return super()._prepare_action()

    def _post_action(self) -> action.ActionResult:
        repofiles = _find_mariadb_repo_files()
        if len(repofiles) == 0:
            return action.ActionResult()

        for repofile in repofiles:
            leapp_configs.adopt_repositories(
                repofile,
                do_adapt_repository=partial(get_adapted_repository, keep_id=True))

        return super()._post_action()

    def estimate_prepare_time(self) -> int:
        return 30

    def estimate_post_time(self) -> int:
        return 60


class AddMysqlConnector(action.ActiveAction):
    def __init__(self) -> None:
        self.name = "install mysql connector"

    def _is_required(self) -> bool:
        return mariadb.is_mysql_installed()

    def _prepare_action(self) -> action.ActionResult:
        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        subprocess.check_call(["/usr/bin/dnf", "install", "-y", "mariadb-connector-c"])
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        return action.ActionResult()


class AssertMysqlCommunityNotInstalled(action.CheckAction):
    """MySQL Community has no upgrade path to AlmaLinux 10.

    AlmaLinux 9 ships MySQL Community as 'mysql-server', AlmaLinux 10 renamed
    it to 'mysql8.4-server' and provides 'mysql-server-any' instead of the
    unversioned name. The Plesk package for MySQL Community on AlmaLinux 10
    still requires 'mysql-server', which nothing provides there, so the
    conversion would remove the database server instead of upgrading it.
    """

    def __init__(self) -> None:
        self.name = "checking MySQL Community is not installed"
        self.description = """The server uses MySQL Community, which cannot be upgraded to AlmaLinux 10.
\tAlmaLinux 10 renamed the packages from 'mysql-server' to 'mysql8.4-server', and the
\tPlesk package for MySQL Community on AlmaLinux 10 still requires the old name, so the
\tconversion would remove the database server and the databases would become unavailable.
\tMigrate the server to MariaDB before the conversion, or wait until Plesk supports
\tMySQL Community on AlmaLinux 10.
"""

    def _do_check(self) -> bool:
        if not mariadb.is_mysql_installed():
            return True

        log.debug("MySQL Community is installed, the conversion is not possible")
        return False
