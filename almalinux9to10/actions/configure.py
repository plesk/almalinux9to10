# Copyright 1999 - 2026. WebPros International GmbH. All rights reserved.

import os
import re
import shutil
import subprocess
import typing
import urllib.request
from functools import partial

from pleskdistup.common import action, leapp_configs, files, log, rpm, selinux, util
from . import common
from .common import get_adapted_repository


class PrepareLeappConfigurationBackup(action.ActiveAction):
    leapp_configs: typing.List[str]

    def __init__(self) -> None:
        self.name = "prepare leapp configuration backup"
        self.leapp_configs = ["/etc/leapp/files/leapp_upgrade_repositories.repo",
                              "/etc/leapp/files/repomap.csv",
                              "/etc/leapp/files/repomap.json",
                              "/etc/leapp/files/pes-events.json"]

    def _prepare_action(self) -> action.ActionResult:
        for file in self.leapp_configs:
            if os.path.exists(file):
                files.backup_file(file)

        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        for file in self.leapp_configs:
            if os.path.exists(file):
                files.remove_backup(file)

        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        for file in self.leapp_configs:
            if os.path.exists(file):
                files.restore_file_from_backup(file)

        return action.ActionResult()


class PleskMainRepoTemporary(action.ActiveAction):

    def __init__(self) -> None:
        self.name = "temporarily create Plesk main repository"
        self.repo_filepath = "/etc/yum.repos.d/plesk-convert_tmp.repo"

    def _create_temporary_plesk_repo(self, repofiles: typing.List[str],
                                     repo_filepath: str) -> str:
        with open(repo_filepath, 'w') as repo_file:
            repo_file.write("# Automatically generated (temporary) by Plesk distribution upgrade script\n")
            for file in repofiles:
                if not os.path.exists(file):
                    continue

                for repo in rpm.extract_repodata(file):
                    if repo.enabled == "0":
                        continue
                    if repo.id is None or repo.name is None or repo.url is None \
                            or not repo.id.startswith("PLESK_18_0") \
                            or "extras" not in repo.id:
                        continue

                    # The repository id has to match the one recorded by rpm as the
                    # origin of the installed Plesk packages ('PLESK_18_0_XX-dist').
                    # Leapp maps repositories by their source id, so an id that does
                    # not match leaves every Plesk package unmapped: they are then
                    # missing from the upgrade transaction and get erased instead of
                    # upgraded, together with the databases the plesk-core %preun
                    # removal branch drops.
                    dist_repo = rpm.Repository(
                        repo.id.replace("-extras", "-dist"),
                        name=repo.name.replace("extras", "dist"),
                        url=repo.url.replace("extras", "dist"),
                        metalink=None,
                        mirrorlist=None,
                        enabled="1\n",
                        gpgcheck="1\n",
                    )
                    repo_file.write(repr(dist_repo))
                    return dist_repo.id
        return ''

    def _prepare_action(self) -> action.ActionResult:
        repofiles = files.find_files_case_insensitive("/etc/yum.repos.d", ["plesk*.repo"])
        self._create_temporary_plesk_repo(repofiles, self.repo_filepath)
        # We need this update since plesk installer will not upgrade "same-version" packages
        # so these packages might be stuck at old DSA/SHA1 signed
        util.logged_check_call(["/usr/bin/dnf", "-y", "update", "--disablerepo=elevate"])
        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        if os.path.exists(self.repo_filepath):
            os.unlink(self.repo_filepath)
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        if os.path.exists(self.repo_filepath):
            os.unlink(self.repo_filepath)
        return action.ActionResult()

    def estimate_prepare_time(self) -> int:
        return 10


class LeappReposConfiguration(action.ActiveAction):

    def __init__(self) -> None:
        self.name = "map plesk repositories for leapp"

    def _prepare_action(self) -> action.ActionResult:
        # The Plesk repositories are adopted as a leapp vendor below. Mapping them
        # here as well would define the same target repositories twice inside the
        # upgrade container, which leapp refuses with
        # "A YUM/DNF repository defined multiple times".
        repofiles = files.find_files_case_insensitive("/etc/yum.repos.d", ["epel.repo"])

        leapp_configs.add_repositories_mapping_json(repofiles, ignore=[
            "PLESK_17_PHP52", "PLESK_17_PHP53", "PLESK_17_PHP54", "PLESK_17_PHP55",
            # Source and debuginfo repositories carry no packages the conversion
            # could install. Mapping them only makes leapp enable more repositories
            # inside the target userspace container, which costs memory during the
            # dnf dependency resolution and adds failure surface for no benefit.
            "epel-source", "epel-debuginfo",
            "epel-testing-source", "epel-testing-debuginfo",
            "epel-cisco-openh264-source", "epel-cisco-openh264-debuginfo"],
                                               do_adapt_repository=partial(get_adapted_repository, keep_id=False),
                                               mapjson_path=leapp_configs.LEAPP_MAP_JSON_PATH,
                                               distro="almalinux",
                                               source_major_version="9",
                                               target_major_version="10")

        # Plesk packages are signed by the Plesk key, so leapp considers them
        # third party and keeps them out of the upgrade transaction no matter how
        # their repositories are mapped. The vendor adoption mechanism is what
        # makes leapp upgrade such packages, the same way it is used for the
        # MariaDB vendor repositories.
        for repofile in files.find_files_case_insensitive("/etc/yum.repos.d", ["plesk*.repo"]):
            log.debug(f"Adopt the Plesk repository file {repofile!r} as a leapp vendor repository")
            leapp_configs.create_leapp_vendor_repository_adoption(
                repofile,
                do_adapt_repository=partial(get_adapted_repository, keep_id=False),
                distro="almalinux",
                source_major_version="9",
                target_major_version="10",
            )

        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        # Since only leap related files should be changed, there is nothing to do after on finishing stage
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        return action.ActionResult()


class UseSystemResolveForLeappContainer(action.ActiveAction):
    path_to_src: str

    def __init__(self) -> None:
        self.name = "configure leapp container to use host's /etc/resolv.conf"
        self.path_to_resolve = "/etc/resolv.conf"
        self.path_to_src = "/etc/leapp/files/resolv.conf"

    def is_required(self) -> bool:
        return os.path.exists(self.path_to_resolve)

    def _prepare_action(self) -> action.ActionResult:
        shutil.copy(self.path_to_resolve, self.path_to_src)
        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        return action.ActionResult()


LEAPP_GPG_KEYS_STORE = "/etc/leapp/files/vendors.d/rpm-gpg"


class FetchEpelGPGKeyForTarget(action.ActiveAction):
    """Provide the EPEL 10 GPG key the adapted repositories point to.

    The repository mapping rewrites 'RPM-GPG-KEY-EPEL-9' into
    'RPM-GPG-KEY-EPEL-10', but nothing on an AlmaLinux 9 host provides that
    file, so leapp reports 'Failed to read GPG keys from provided key files'
    and refuses to import the key during the conversion.
    """

    EPEL_KEY_URL = "https://dl.fedoraproject.org/pub/epel/RPM-GPG-KEY-EPEL-10"
    EPEL_KEY_PATH = "/etc/pki/rpm-gpg/RPM-GPG-KEY-EPEL-10"
    GPG_KEY_HEADER = "-----BEGIN PGP PUBLIC KEY BLOCK-----"

    def __init__(self) -> None:
        self.name = "fetching the EPEL 10 GPG key"

    def _is_required(self) -> bool:
        return (
            len(files.find_files_case_insensitive("/etc/yum.repos.d", ["epel*.repo"])) > 0
            and not os.path.exists(self.EPEL_KEY_PATH)
        )

    def _prepare_action(self) -> action.ActionResult:
        try:
            with urllib.request.urlopen(self.EPEL_KEY_URL, timeout=30) as response:
                key = response.read()
        except Exception as ex:
            raise RuntimeError(
                f"Unable to fetch the EPEL 10 GPG key from {self.EPEL_KEY_URL!r}: {ex}. "
                f"To continue with the conversion, download the key into {self.EPEL_KEY_PATH!r} manually."
            ) from ex

        # Make sure we store a key and not an error page served with code 200
        if not key.startswith(self.GPG_KEY_HEADER.encode()):
            raise RuntimeError(
                f"The data fetched from {self.EPEL_KEY_URL!r} is not a GPG key. "
                f"To continue with the conversion, download the key into {self.EPEL_KEY_PATH!r} manually."
            )

        with open(self.EPEL_KEY_PATH, "wb") as key_file:
            key_file.write(key)

        # Keys in the leapp vendor store are trusted during the conversion
        os.makedirs(LEAPP_GPG_KEYS_STORE, exist_ok=True)
        shutil.copy(self.EPEL_KEY_PATH, os.path.join(LEAPP_GPG_KEYS_STORE, os.path.basename(self.EPEL_KEY_PATH)))
        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        if os.path.exists(self.EPEL_KEY_PATH):
            os.unlink(self.EPEL_KEY_PATH)
        return action.ActionResult()

    def estimate_prepare_time(self) -> int:
        return 5


class ProvidePleskGPGKeyFile(action.ActiveAction):
    """Store the Plesk GPG key as a file the adapted repositories can point to.

    Plesk repositories use 'gpgcheck=1' without a 'gpgkey=' entry and rely on
    the key being imported into the host RPM database. Leapp refuses to install
    packages from a target repository that provides no key, so without this the
    Plesk packages have no upgrade path during the conversion and get erased
    instead, which triggers the database dropping branch of the plesk-core
    %preun scriptlet.

    The key is taken from the RPM database, so it is the one that actually
    signed the installed packages, whichever mirror they came from. Downloading
    from autoinstall.plesk.com is only a fallback.
    """

    FALLBACK_KEY_URL = "https://autoinstall.plesk.com/plesk.gpg"
    KEY_SUMMARY_REGEXP = r"(Plesk|Parallels|WebPros|SWsoft)"
    GPG_KEY_HEADER = "-----BEGIN PGP PUBLIC KEY BLOCK-----"

    def __init__(self) -> None:
        self.name = "providing the Plesk GPG key file"

    def _is_required(self) -> bool:
        return not os.path.exists(common.PLESK_GPG_KEY_PATH)

    def _store_key_from_url(self) -> None:
        log.info(f"Plesk GPG key not found in the RPM database, fetching it from {self.FALLBACK_KEY_URL!r}")
        try:
            with urllib.request.urlopen(self.FALLBACK_KEY_URL, timeout=30) as response:
                key = response.read()
        except Exception as ex:
            raise RuntimeError(
                f"Unable to fetch the Plesk GPG key from {self.FALLBACK_KEY_URL!r}: {ex}. To continue with the "
                f"conversion, store the key of your Plesk repositories in {common.PLESK_GPG_KEY_PATH!r} manually."
            ) from ex

        # Make sure we store a key and not an error page served with code 200
        if not key.startswith(self.GPG_KEY_HEADER.encode()):
            raise RuntimeError(
                f"The data fetched from {self.FALLBACK_KEY_URL!r} is not a GPG key. To continue with the "
                f"conversion, store the key of your Plesk repositories in {common.PLESK_GPG_KEY_PATH!r} manually."
            )

        with open(common.PLESK_GPG_KEY_PATH, "wb") as key_file:
            key_file.write(key)

    def _prepare_action(self) -> action.ActionResult:
        if not rpm.extract_gpgkey_from_rpm_database(self.KEY_SUMMARY_REGEXP, common.PLESK_GPG_KEY_PATH):
            self._store_key_from_url()

        # Keys in the leapp vendor store are trusted during the conversion
        os.makedirs(LEAPP_GPG_KEYS_STORE, exist_ok=True)
        shutil.copy(common.PLESK_GPG_KEY_PATH, os.path.join(LEAPP_GPG_KEYS_STORE, os.path.basename(common.PLESK_GPG_KEY_PATH)))
        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        if os.path.exists(common.PLESK_GPG_KEY_PATH):
            os.unlink(common.PLESK_GPG_KEY_PATH)
        return action.ActionResult()

    def estimate_prepare_time(self) -> int:
        return 5


class ProvidePleskVendorSignatures(action.ActiveAction):
    """Declare the signing keys of the Plesk packages to leapp.

    Leapp keeps packages that are not signed by the distribution vendor out of
    the upgrade transaction. A vendor is recognized by a '<vendor>.sigs' file in
    the vendors.d directory listing the key ids its packages are signed with.
    The leapp data package ships such files for the vendors it knows about
    (mariadb, imunify, kernelcare and so on) but not for Plesk.

    The key ids are read from the installed packages rather than hardcoded, so
    the conversion follows whatever key signed the packages on this server.
    """

    PACKAGE_GLOBS = ["plesk-*", "psa-*", "sw-engine*"]
    VENDOR_REPO_FILES = ["plesk.repo", "plesk-convert_tmp.repo"]
    # 'RSA/SHA256, Tue 01 Sep 2026 06:52:11 AM UTC, Key ID 6a71ab3a1cd93cca'
    KEY_ID_REGEX = re.compile(r"Key ID ([0-9a-fA-F]{8,40})")

    def __init__(self) -> None:
        self.name = "declaring the Plesk package signatures for leapp"

    def _get_signature_key_ids(self) -> typing.List[str]:
        key_ids: typing.List[str] = []
        try:
            signatures = subprocess.check_output(
                ["/usr/bin/rpm", "-q", "--qf", "%{SIGPGP:pgpsig}\n"] + self.PACKAGE_GLOBS,
                universal_newlines=True, stderr=subprocess.DEVNULL,
            ).splitlines()
        except subprocess.CalledProcessError as ex:
            log.warn(f"Unable to read the signatures of the installed Plesk packages: {ex}")
            return key_ids

        for signature in signatures:
            match = self.KEY_ID_REGEX.search(signature)
            if match is not None and match.group(1).lower() not in key_ids:
                key_ids.append(match.group(1).lower())

        return key_ids

    def _is_required(self) -> bool:
        return len(self._get_signature_key_ids()) > 0

    def _prepare_action(self) -> action.ActionResult:
        key_ids = self._get_signature_key_ids()
        if not key_ids:
            # Unsigned packages carry no key to declare. AssertPleskPackagesSigned
            # refuses the conversion in that case unless the unsigned packages were
            # explicitly allowed, in which case leapp is told to treat every package
            # as signed instead.
            log.warn("The installed Plesk packages are not signed, no vendor signatures to declare")
            return action.ActionResult()

        os.makedirs(leapp_configs.LEAPP_VENDORS_DIR_PATH, exist_ok=True)
        for repofile in self.VENDOR_REPO_FILES:
            sigfile = os.path.join(leapp_configs.LEAPP_VENDORS_DIR_PATH, repofile.replace(".repo", ".sigs"))
            log.info(f"Writing the Plesk package signing keys {key_ids} into {sigfile!r}")
            with open(sigfile, "w") as dst:
                dst.write("\n".join(key_ids) + "\n")

        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        for repofile in self.VENDOR_REPO_FILES:
            sigfile = os.path.join(leapp_configs.LEAPP_VENDORS_DIR_PATH, repofile.replace(".repo", ".sigs"))
            if os.path.exists(sigfile):
                os.unlink(sigfile)
        return action.ActionResult()

    def estimate_prepare_time(self) -> int:
        return 1


class LoadPleskSelinuxPolicy(action.ActiveAction):
    """Load the Plesk SELinux policy modules after the conversion.

    Plesk ships its SELinux policy in /usr/local/psa/etc/*.pp and loads it from
    the psa-selinux package scripts. During the conversion that package is
    upgraded inside the leapp container, where 'semodule' cannot work, so the
    modules are never loaded on the target OS. Leapp relabels the filesystem
    with the stock policy on top of that, and the result is a server where the
    Plesk ports and file contexts are unknown: Apache cannot bind port 7080,
    which also fails plesk-ip-remapping.service and httpd-init.service.
    """

    POLICY_MODULES_DIR = "/usr/local/psa/etc"
    SEMODULE_BIN = "/usr/sbin/semodule"

    def __init__(self) -> None:
        self.name = "loading the Plesk SELinux policy modules"

    def _get_policy_modules(self) -> typing.List[str]:
        return sorted(files.find_files_case_insensitive(self.POLICY_MODULES_DIR, ["*.pp"]))

    def _is_required(self) -> bool:
        return (
            selinux.get_configured_mode() is not selinux.SelinuxMode.DISABLED
            and os.path.exists(self.SEMODULE_BIN)
            and len(self._get_policy_modules()) > 0
        )

    def _prepare_action(self) -> action.ActionResult:
        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        modules = self._get_policy_modules()
        log.info(f"Loading the Plesk SELinux policy modules: {modules}")
        command = [self.SEMODULE_BIN]
        for module in modules:
            command += ["-i", module]

        util.logged_check_call(command)
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        return action.ActionResult()

    def estimate_post_time(self) -> int:
        return 30
