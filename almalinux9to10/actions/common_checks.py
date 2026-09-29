# Copyright 1999 - 2026. WebPros International GmbH. All rights reserved.

import os
import re
import subprocess
import typing

from pleskdistup.common import action, dist, files, log, plesk, rpm, version


class AssertDistroIsAlmaLinux10(action.CheckAction):
    def __init__(self) -> None:
        self.name = "checking if distro is AlmaLinux 10"
        self.description = "You are running a distribution other than AlmaLinux 10. The finalization stage can only be started on AlmaLinux 10."

    def _do_check(self) -> bool:
        return dist.get_distro() == dist.AlmaLinux("10")


class AssertNoMoreThenOneKernelNamedNIC(action.CheckAction):
    def __init__(self) -> None:
        self.name = "checking if there is more than one NIC interface using ketnel-name"
        self.description = """The system has one or more network interface cards (NICs) using kernel-names (ethX).
\tLeapp cannot guarantee the interface names' stability during the conversion.
\tGive those NICs persistent names (enpXsY) to proceed with the conversion.
\tInterfaces: {}
"""

    def _do_check(self) -> bool:
        # We can't use this method to get interfaces names, so just skip the check
        if not os.path.exists("/sys/class/net"):
            return True

        interfaces = os.listdir('/sys/class/net')
        suspicious_interfaces = [interface for interface in interfaces if interface.startswith("eth") and interface[3:].isdigit()]
        if len(suspicious_interfaces) > 1:
            self.description = self.description.format(", ".join(suspicious_interfaces))
            return False

        return True


# ToDo. Implement for deb-based and move to common part. Might be useful for distupgrade/other converters
class AssertLastInstalledKernelInUse(action.CheckAction):
    def __init__(self) -> None:
        self.name = "checking if the last installed kernel is in use"
        self.description = """The last installed kernel is not in use.
\tThe kernel version in use is '{}'. The last installed kernel version is '{}'.
\tReboot the system to use the last installed kernel.
"""

    def _get_kernel_version_in_use(self) -> version.KernelVersion:
        curr_kernel = subprocess.check_output(["/usr/bin/uname", "-r"], universal_newlines=True).strip()
        log.debug("Current kernel version is '{}'".format(curr_kernel))
        return version.KernelVersion(curr_kernel)

    def _get_last_installed_kernel_version(self) -> version.KernelVersion:
        versions = subprocess.check_output(
            [
                "/usr/bin/rpm", "-q", "-a", "kernel", "kernel-plus", "kernel-rt-core"
            ], universal_newlines=True
        ).splitlines()

        log.debug("Installed kernel versions: {}".format(', '.join(versions)))
        return max([version.KernelVersion(ver) for ver in versions])

    def _do_check(self) -> bool:
        last_installed_kernel_version = self._get_last_installed_kernel_version()
        used_kernel_version = self._get_kernel_version_in_use()

        if used_kernel_version != last_installed_kernel_version:
            self.description = self.description.format(str(used_kernel_version), str(last_installed_kernel_version))
            return False

        return True


class AssertRedHatKernelInstalled(action.CheckAction):
    def __init__(self) -> None:
        self.name = "checking if the Red Hat kernel is installed"
        self.description = """No Red Hat signed kernel is installed.
\tTo proceed with the conversion, install a kernel by running:
\t- 'yum install kernel kernel-tools kernel-tools-libs'
\tAfter installing the kernel fix the grub configuration by calling:
\t- `grub2-set-default 'AlmaLinux (newly_installed_kernel_version) 9 (Core)'`
\t- `grub2-mkconfig -o /boot/grub2/grub.cfg`
\t- `reboot`
"""

    def _do_check(self) -> bool:
        redhat_kernel_packages = subprocess.check_output(
            [
                "/usr/bin/rpm", "-q", "-a", "kernel", "kernel-rt"
            ], universal_newlines=True
        ).splitlines()
        return len(redhat_kernel_packages) > 0


class AssertPackagesUpToDate(action.CheckAction):
    def __init__(self):
        self.name = "checking if all packages are up to date"
        self.description = "There are packages which are not up to date. Call `yum update -y && reboot` to update the packages.\n"

    def _do_check(self) -> bool:
        subprocess.check_call(["/usr/bin/yum", "clean", "all"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        checker = subprocess.run(["/usr/bin/yum", "check-update"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return checker.returncode == 0


class AssertNoOldRPMSignatures(action.CheckAction):
    _fail_for_plesk_packages: bool

    def __init__(self, fail_for_plesk_packages: bool = True):
        self._fail_for_plesk_packages = fail_for_plesk_packages
        self.name = "checking if all RPMs have modern SHA256 signing"
        self.description = "There are packages which are signed with old methods.\n\t"

    @classmethod
    def _could_be_leftover_package(cls, pkg_name: str, include_php: bool = False) -> bool:
        return ((pkg_name.startswith('plesk-php') if include_php else False) or
                (pkg_name.startswith('plesk-') and not pkg_name.startswith('plesk-php')) or
                pkg_name.startswith('psa-') or
                pkg_name.startswith('sw-') or
                (pkg_name.startswith('pp') and pkg_name.endswith('-bootstrapper')))

    def _do_check(self) -> bool:
        packs = rpm.get_packages_with_sign_method('DSA/SHA1')
        if not packs:
            return True

        plesk_packs = []
        other_packs = []
        for name, ver in packs:
            if self._could_be_leftover_package(name):
                plesk_packs.append((name, ver))
            else:
                other_packs.append((name, ver))

        if self._fail_for_plesk_packages and plesk_packs:
            self.description += "- Found Plesk packages: autoremove those by passing '--rm-sha1-plesk-packages'\n\t"
        if not other_packs and not self._fail_for_plesk_packages:
            return True
        if other_packs:
            self.description += "- Consider remove/reinstall:\n\t\t{}".format(
                ' '.join([f"{name}-{ver}" for name, ver in other_packs]))
        return False


class AssertCgroupsV2Enabled(action.CheckAction):
    def __init__(self) -> None:
        self.name = "checking if cgroups-v2 is in use"
        self.description = """The system is booted with cgroups-v1 enabled.
\tSupport for cgroups-v1 was deprecated in AlmaLinux 9 and is removed in AlmaLinux 10,
\tso leapp will refuse the conversion. Make sure no third party software requires
\tcgroups-v1 and drop the kernel arguments by calling:
\t- `grubby --update-kernel=ALL --remove-args="{}"`
\t- `reboot`
"""

    def _do_check(self) -> bool:
        cmdline_path = "/proc/cmdline"
        if not os.path.exists(cmdline_path):
            return True

        with open(cmdline_path) as f:
            parameters = f.read().split()

        unified_hierarchy = True  # default since AlmaLinux 9
        arguments_to_remove: typing.List[str] = []
        for parameter in parameters:
            key, _, value = parameter.partition("=")
            if key == "systemd.unified_cgroup_hierarchy":
                if value.lower() in ("0", "false", "no"):
                    unified_hierarchy = False
                    arguments_to_remove.append(key)
            elif key == "systemd.legacy_systemd_cgroup_controller":
                # No matter the value, it has no effect with the unified hierarchy
                # enabled, so leapp expects it to be removed as well.
                arguments_to_remove.append(key)

        if unified_hierarchy:
            return True

        self.description = self.description.format(" ".join(arguments_to_remove))
        return False


class AssertXfsFilesystemsSupported(action.CheckAction):
    XFS_INFO_PATH = "/usr/sbin/xfs_info"

    def __init__(self) -> None:
        self.name = "checking if XFS filesystems are supported by the target OS"
        self.description = """The following XFS filesystems lack features required by AlmaLinux 10: {}
\tXFS filesystems without the 'crc' (v4 format) or the 'bigtime' feature are not
\tsupported by AlmaLinux 10 and leapp will refuse the conversion. Filesystems created
\ton AlmaLinux 8 usually lack 'bigtime', so servers converted from AlmaLinux 8 are affected.
\tThe 'bigtime' feature can be enabled without recreating the filesystem, but only while it
\tis not mounted, so for the root filesystem it has to be done from a rescue boot or with
\tthe disk attached to another server:
\t- `xfs_admin -O bigtime=1 <device>`
\t- `xfs_info <device>` to verify the result
\tFilesystems without 'crc' use the old v4 format, which cannot be upgraded at all: those
\thave to be backed up, recreated with 'mkfs.xfs' and restored before the conversion.
"""

    def _get_xfs_mountpoints(self) -> typing.List[str]:
        mountpoints = []
        try:
            with open("/proc/mounts") as mounts:
                for line in mounts:
                    parts = line.split()
                    if len(parts) > 2 and parts[2] == "xfs":
                        mountpoints.append(parts[1])
        except OSError as ex:
            log.warn(f"Unable to read /proc/mounts to find XFS filesystems: {ex}")

        return mountpoints

    def _is_mountpoint_supported(self, mountpoint: str) -> bool:
        try:
            info = subprocess.check_output(
                [self.XFS_INFO_PATH, mountpoint], universal_newlines=True,
                stderr=subprocess.DEVNULL,
            )
        except (subprocess.CalledProcessError, OSError) as ex:
            log.warn(f"Unable to get xfs_info for {mountpoint!r}: {ex}")
            # Don't prevent the conversion when we can't tell, leapp will check it anyway
            return True

        for feature in ("crc", "bigtime"):
            for match in re.findall(rf"\b{feature}=(\S+)", info):
                if match.rstrip(",") == "0":
                    log.debug(f"Mountpoint {mountpoint!r} has {feature}=0")
                    return False

        return True

    def _do_check(self) -> bool:
        if not os.path.exists(self.XFS_INFO_PATH):
            log.warn(f"{self.XFS_INFO_PATH} is not available, skip the XFS features check")
            return True

        unsupported = [
            mountpoint for mountpoint in self._get_xfs_mountpoints()
            if not self._is_mountpoint_supported(mountpoint)
        ]
        if not unsupported:
            return True

        self.description = self.description.format(", ".join(unsupported))
        return False

class AssertEnoughMemoryForLeapp(action.CheckAction):
    """Guard against the leapp target userspace creation being OOM killed.

    Leapp's own checkmemory actor only requires 1.5 GiB of RAM on x86_64, which
    is not enough for a Plesk server: the 'dnf install' leapp runs inside the
    systemd-nspawn container has to resolve every mapped repository at once and
    was observed being OOM killed at a 1.4 GB peak on a host with 1.7 GB of RAM
    and no swap.

    That allocation happens in the target userspace creation, before the reboot
    and on the running system, so swap counts towards the requirement. Physical
    RAM alone still has to satisfy leapp's own minimum.
    """

    required_memory: int
    required_ram: int = 1536 * 1024 * 1024  # leapp's own minimum on x86_64

    def __init__(self, required_memory: int) -> None:
        self.required_memory = required_memory
        self.name = "asserting enough memory for the leapp conversion"
        self.description = """The system has {} GB of RAM and {} GB of swap, which is less than the
\t{} GB of memory required for the conversion. Leapp creates the target OS userspace by
\trunning 'dnf install' inside a container, and on a Plesk server that process is killed
\tby the OOM killer with less memory available.
"""
        self.low_ram_description = """The system has {} GB of RAM, less than the {} GB leapp itself requires.
\tSwap is not taken into account for this requirement.
"""

    def _read_meminfo_value(self, field: str) -> int:
        try:
            with open("/proc/meminfo") as meminfo:
                for line in meminfo:
                    if line.startswith(f"{field}:"):
                        # The values are in KB, convert them to bytes
                        return int(line.split()[1]) * 1024
        except OSError as ex:
            log.warn(f"Unable to read /proc/meminfo: {ex}")

        return 0

    def _do_check(self) -> bool:
        total_ram = self._read_meminfo_value("MemTotal")
        total_swap = self._read_meminfo_value("SwapTotal")
        if total_ram == 0:
            log.warn("Unable to determine the amount of RAM, skip the memory check")
            return True

        if total_ram < self.required_ram:
            self.description = self.low_ram_description.format(
                round(total_ram / 1024 ** 3, 2),
                round(self.required_ram / 1024 ** 3, 2),
            )
            return False

        if total_ram + total_swap >= self.required_memory:
            return True

        self.description = self.description.format(
            round(total_ram / 1024 ** 3, 2),
            round(total_swap / 1024 ** 3, 2),
            round(self.required_memory / 1024 ** 3, 2),
        )
        return False


class AssertEpelRepositoryAvailable(action.CheckAction):
    """Plesk on AlmaLinux 10 needs a package only EPEL provides.

    The el10 plesk-core package requires perl(Digest::SHA1), and the only
    provider for AlmaLinux 10 is perl-Digest-SHA1 from EPEL. Without an EPEL
    repository on the source system leapp has no el10 EPEL to map, plesk-core
    cannot be installed, and the conversion removes the Plesk packages instead
    of upgrading them.
    """

    def __init__(self) -> None:
        self.name = "checking the EPEL repository is available"
        self.description = """The EPEL repository is not configured, but it is required for the conversion.
\tPlesk on AlmaLinux 10 requires 'perl(Digest::SHA1)', which is only provided by the
\t'perl-Digest-SHA1' package from EPEL. Without it the Plesk packages cannot be upgraded
\tand would be removed during the conversion.
\tInstall the repository before the conversion by calling:
\t- `dnf install -y epel-release`
"""

    def _do_check(self) -> bool:
        if not plesk.is_plesk_database_ready():
            return True

        for repofile in files.find_files_case_insensitive("/etc/yum.repos.d", ["*.repo"]):
            for repo in rpm.extract_repodata(repofile):
                if repo.id is None or not repo.id.lower().startswith("epel"):
                    continue
                if repo.enabled is None or repo.enabled.strip() != "0":
                    log.debug(f"Found enabled EPEL repository {repo.id!r} in {repofile!r}")
                    return True

        return False


class AssertNoPackageExcludes(action.CheckAction):
    """Package exclude filters break the conversion in non-obvious ways.

    An 'exclude' in the dnf configuration or an 'excludepkgs' in a repository
    file keeps the filtered packages out of every transaction, including the
    ones the conversion performs on the target OS. A package excluded because
    of a conflict on AlmaLinux 9 is usually not a problem on AlmaLinux 10, but
    the filter stays in place and the finish stage then cannot install the
    packages that depend on it.
    """

    DNF_CONFIG = "/etc/dnf/dnf.conf"
    YUM_CONFIG = "/etc/yum.conf"

    def __init__(self) -> None:
        self.name = "checking no packages are excluded from the package manager"
        self.description = """Packages are excluded from the package manager configuration: {}
\tThe exclusions also apply to the transactions performed on AlmaLinux 10, where the
\tconversion has to install the target OS versions of the excluded packages and of
\teverything depending on them.
\tRemove the exclusions before the conversion.
"""

    def _get_excludes(self) -> typing.List[str]:
        found = []

        for config in (self.DNF_CONFIG, self.YUM_CONFIG):
            if not os.path.exists(config):
                continue
            try:
                with open(config) as conf:
                    for line in conf:
                        stripped = line.strip()
                        if stripped.startswith("exclude") and "=" in stripped:
                            value = stripped.split("=", 1)[1].strip()
                            if value:
                                found.append(f"{config}: {stripped}")
            except OSError as ex:
                log.warn(f"Unable to read {config!r}: {ex}")

        for repofile in files.find_files_case_insensitive("/etc/yum.repos.d", ["*.repo"]):
            try:
                with open(repofile) as conf:
                    for line in conf:
                        stripped = line.strip()
                        if stripped.startswith(("exclude=", "excludepkgs=")) and stripped.split("=", 1)[1].strip():
                            found.append(f"{repofile}: {stripped}")
            except OSError as ex:
                log.warn(f"Unable to read {repofile!r}: {ex}")

        return found

    def _do_check(self) -> bool:
        excludes = self._get_excludes()
        if not excludes:
            return True

        self.description = self.description.format("\n\t- " + "\n\t- ".join(excludes))
        return False
