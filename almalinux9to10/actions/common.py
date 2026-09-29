# Copyright 1999 - 2026. WebPros International GmbH. All rights reserved.
import os
import shutil
import subprocess
import typing

from pleskdistup.common import action, dns, files, leapp_configs, log, motd, rpm, util


# Plesk repositories are configured with 'gpgcheck=1' but without any 'gpgkey='
# entry: the key is expected to be already imported into the host RPM database.
# Leapp requires the target repository definition itself to provide a key and
# refuses to install packages from a repository that does not, which leaves the
# installed Plesk packages without an upgrade path. Dnf then resolves the
# transaction by erasing them, and the removal branch of the plesk-core %preun
# scriptlet tries to drop the Plesk databases. So the adapted repositories get
# an explicit key, extracted from the RPM database by ProvidePleskGPGKeyFile.
PLESK_GPG_KEY_PATH = "/etc/pki/rpm-gpg/RPM-GPG-KEY-plesk"
PLESK_GPG_KEY_URL = f"file://{PLESK_GPG_KEY_PATH}"


def _is_plesk_repository(id: typing.Optional[str]) -> bool:
    return id is not None and "PLESK" in id.upper()


def _do_id_replacement(id: typing.Optional[str]) -> typing.Optional[str]:
    if id is not None:
        id = id.replace("alma9-", "")
    return leapp_configs.do_replacement(id, [
        lambda to_change: "alma10-" + to_change if not to_change.startswith("alma10-") else to_change,
    ])


def _do_name_replacement(name: typing.Optional[str]) -> typing.Optional[str]:
    return leapp_configs.do_replacement(name, [
        lambda to_change: "Alma " + to_change if not to_change.startswith("Alma ") else to_change,
        lambda to_change: to_change.replace("Enterprise Linux 9",  "Enterprise Linux 10"),
        lambda to_change: to_change.replace("EPEL-9", "EPEL-10"),
        lambda to_change: to_change.replace("$releasever", "10"),
    ])


def _fix_rackspace_repository(to_change: str) -> str:
    if "mirror.rackspace.com" in to_change:
        return to_change.replace("rhel9-amd64", "rhel10-amd64")
    return to_change


def _fix_mariadb_repository(to_change: str) -> str:
    # MariaDB official repository provides short 'rhelX' urls for every supported
    # version, so the rhel9 -> rhel10 substitution is enough here.
    if "yum.mariadb.org" in to_change:
        return to_change.replace("rhel9", "rhel10")
    return to_change


def _fix_rackspace_epel_repository(to_change: str) -> str:
    # The Rackspace EPEL repository for version 9 has a slightly different path, including 'Everything' in it
    # Additionally, some repositories use '9Server' instead of 9.
    # Therefore, we need to handle these cases specifically.
    if "iad.mirror.rackspace.com/epel/9/Everything" in to_change:
        return to_change.replace("9/Everything", "10/Everything")
    if "iad.mirror.rackspace.com/epel/9Server" in to_change:
        return to_change.replace("9Server", "10/Everything")
    if "iad.mirror.rackspace.com/epel/9/" in to_change:
        return to_change.replace("epel/9/", "epel/10/Everything/")
    return to_change


def _do_url_replacement(url: typing.Optional[str]) -> typing.Optional[str]:
    return leapp_configs.do_replacement(url, [
        _fix_rackspace_repository,
        _fix_mariadb_repository,
        _fix_rackspace_epel_repository,
        lambda to_change: to_change.replace("archives.fedoraproject.org/pub/archive/epel/9", "dl.fedoraproject.org/pub/epel/10/Everything"),
        lambda to_change: to_change.replace("rpm-RedHat-el9", "rpm-RedHat-el10"),
        lambda to_change: to_change.replace("AlmaLinux-9", "AlmaLinux-10"),
        lambda to_change: to_change.replace("almalinux/9", "almalinux/10"),
        lambda to_change: to_change.replace("epel-9", "epel-10"),
        lambda to_change: to_change.replace("epel/9", "epel/10"),
        lambda to_change: to_change.replace("epel-debug-9", "epel-debug-10"),
        lambda to_change: to_change.replace("epel-source-9", "epel-source-10"),
        lambda to_change: to_change.replace("centos9", "centos10"),
        lambda to_change: to_change.replace("almalinux9", "almalinux10"),
        lambda to_change: to_change.replace("centos/9", "centos/10"),
        lambda to_change: to_change.replace("rhel/9", "rhel/10"),
        lambda to_change: to_change.replace("rhel9", "rhel10"),
        lambda to_change: to_change.replace("CentOS_9", "CentOS_10"),
        lambda to_change: to_change.replace("AlmaLinux_9", "AlmaLinux_10"),
        lambda to_change: to_change.replace("rhel-$releasever", "rhel-10"),
        lambda to_change: to_change.replace("$releasever", "10"),
        lambda to_change: to_change.replace("mirror.pp.plesk.tech/almalinux/9/almalinux-x86_64-server-9/", "mirror.pp.plesk.tech/almalinux/10/almalinux-x86_64-server-10/"),
        lambda to_change: to_change.replace("mirror.pp.plesk.tech/almalinux/9/os/", "mirror.pp.plesk.tech/almalinux/10/almalinux-x86_64-server-10/"),
        lambda to_change: to_change.replace("autoinstall.plesk.com/PMM_0.1.10", "autoinstall.plesk.com/PMM_1.1.1"),
        lambda to_change: to_change.replace("autoinstall.plesk.com/PMM_0.1.11", "autoinstall.plesk.com/PMM_1.1.1"),
        lambda to_change: to_change.replace("autoinstall.plesk.com/PMM_1.0.0", "autoinstall.plesk.com/PMM_1.1.1"),
        lambda to_change: to_change.replace("autoinstall.plesk.com/PMM0", "autoinstall.plesk.com/PMM_1.1.1"),
    ])


def _do_gpgkey_replacement(gpgkey: typing.Optional[str]) -> typing.Optional[str]:
    return leapp_configs.do_replacement(gpgkey, [
        lambda to_change: to_change.replace("EPEL-9", "EPEL-10"),
    ])


def _do_common_replacement(line: typing.Optional[str]) -> typing.Optional[str]:
    return leapp_configs.do_replacement(line, [
        lambda to_change: to_change.replace("EPEL-9", "EPEL-10"),
    ])


def get_adapted_repository(
        repository: rpm.Repository,
        keep_id: bool = False
) -> rpm.Repository:
    id = _do_id_replacement(repository.id) if not keep_id else repository.id
    name = _do_name_replacement(repository.name)

    if id is None or name is None:
        raise ValueError(f"Repository {repository.id!r} with name {name!r} has no next id or next name")

    if repository.url is None and repository.metalink is None and repository.mirrorlist is None:
        raise ValueError(f"Repository {repository.id!r} has no next baseurl, metalink and mirrorlist")

    gpgkey_replacement = [_do_gpgkey_replacement(gpgkey) for gpgkey in repository.gpgkeys] if repository.gpgkeys else []

    if not gpgkey_replacement and _is_plesk_repository(repository.id) and repository.gpgcheck and repository.gpgcheck.strip() != "0":
        gpgkey_replacement = [PLESK_GPG_KEY_URL]

    return rpm.Repository(
        id,
        name=name,
        url=_do_url_replacement(repository.url) if repository.url else None,
        metalink=_do_url_replacement(repository.metalink) if repository.metalink else None,
        mirrorlist=_do_url_replacement(repository.mirrorlist) if repository.mirrorlist else None,
        enabled=repository.enabled,
        gpgcheck=repository.gpgcheck,
        gpgkeys=[gpgkey for gpgkey in gpgkey_replacement if gpgkey is not None] if gpgkey_replacement else None,
        additional=[sline for sline in (_do_common_replacement(line) for line in repository.additional) if sline is not None]
    )


class DisablePesEventsRemovePackages(action.ActiveAction):
    _list_of_packages_to_remove: typing.List[str]
    _repos: typing.Optional[typing.List[str]]

    def __init__(self, list_of_packages_to_remove: typing.List[str], repos: typing.Optional[typing.List[str]] = None):
        self.name = "disable PES events and remove related packages"
        self._list_of_packages_to_remove = list_of_packages_to_remove
        self._repos = repos

    def _prepare_action(self) -> action.ActionResult:
        if os.path.exists(leapp_configs.LEAPP_PKGS_CONF_PATH):
            files.backup_file(leapp_configs.LEAPP_PKGS_CONF_PATH)
        else:
            return action.ActionResult()

        for package in self._list_of_packages_to_remove:
            for r in self._repos if self._repos is not None else [None]:
                leapp_configs.rm_package_from_pes_events(package, r)
        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        files.restore_file_from_backup(leapp_configs.LEAPP_PKGS_CONF_PATH)
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        files.restore_file_from_backup(leapp_configs.LEAPP_PKGS_CONF_PATH)
        return action.ActionResult()

