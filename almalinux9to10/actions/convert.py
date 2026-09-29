# Copyright 1999 - 2026. WebPros International GmbH. All rights reserved.
import os
from pleskdistup.common import action, leapp_configs, log, systemd, util

import subprocess
import typing


class LeappPreupgradeRisksPreventedException(Exception):
    def __init__(self, inhibitors: typing.List[str], original_exception: typing.Optional[Exception] = None):
        super().__init__("Leapp preupgrade failed due to preventing factors being found.")
        self.inhibitors = inhibitors
        self.original_exception = original_exception

    def __str__(self):
        inhibitors_str = "\n".join(self.inhibitors)

        original_exception_str = ""
        if self.original_exception is not None:
            original_exception_str = f"Original exception: {self.original_exception}.\n"

        return f"{super().__str__()}\n{original_exception_str}The preventing factors are:\n{inhibitors_str}"


class PleskPackagesRemovalException(Exception):
    def __init__(self, packages: typing.List[str]):
        super().__init__("Leapp is going to remove Plesk packages instead of upgrading them.")
        self.packages = packages

    def __str__(self):
        packages_str = "\n".join(f"\t- {package}" for package in self.packages)
        return (
            f"{super().__str__()}\n"
            "The conversion was stopped because the following Plesk packages are scheduled for removal:\n"
            f"{packages_str}\n"
            "Removing them is not recoverable: the removal branch of the plesk-core scriptlet drops the Plesk "
            "databases, and the server is left without a control panel.\n"
            "This usually means a package the Plesk packages depend on has no counterpart on the target OS. "
            "Check the 'Removing:' section of the leapp transaction in /var/log/leapp/ to find it, and report "
            "the issue with the feedback archive prepared by the '--prepare-feedback' option."
        )


class DoAlmaLinux9to10Convert(action.ActiveAction):
    LEAPP_RESUME_SERVICE = "leapp_resume.service"
    leapp_ovl_size: int
    allow_unsigned_packages: bool

    def __init__(self, leapp_ovl_size: int = 4096, allow_unsigned_packages: bool = False):
        self.name = "doing the conversion"
        self.leapp_ovl_size = leapp_ovl_size
        self.allow_unsigned_packages = allow_unsigned_packages


    # Removing any of these takes the control panel down, and plesk-core drops the
    # Plesk databases from the removal branch of its %preun scriptlet.
    CRITICAL_PACKAGES = ("plesk-core", "psa", "sw-engine", "plesk-engine", "plesk-control-panel")
    # Other Plesk packages are only worth a warning: single leaf packages without a
    # counterpart on the target OS are dropped even by a successful conversion.
    PLESK_PACKAGE_PREFIXES = ("plesk", "psa-", "psa.", "sw-engine", "pp18")
    LEAPP_LOG_PATHS = ["/var/log/leapp/leapp-upgrade.log", "/var/log/leapp/leapp-preupgrade.log"]
    # Section headers of the dnf transaction leapp prints during its checks
    REMOVAL_SECTIONS = ("Removing:", "Removing dependent packages:")

    def _get_leapp_transaction_log(self) -> typing.Optional[str]:
        existing = [path for path in self.LEAPP_LOG_PATHS if os.path.exists(path)]
        if not existing:
            return None
        return max(existing, key=os.path.getmtime)

    def _get_packages_scheduled_for_removal(self, log_path: str) -> typing.List[str]:
        """Read the package names leapp's dnf transaction check is going to remove.

        Leapp's own removal list does not describe this: the packages are erased
        by dnf while resolving the transaction, so the only place they show up is
        the transaction listing in the leapp log.
        """
        removals: typing.List[str] = []
        in_removal_section = False

        with open(log_path) as log_file:
            for line in log_file:
                _, separator, content = line.partition("dnf_transaction_check: ")
                if not separator:
                    continue

                if content.startswith(" "):
                    # A package entry of the section currently being listed
                    if in_removal_section and content.split():
                        removals.append(content.split()[0])
                    continue

                header = content.strip()
                if not header:
                    continue

                if header in self.REMOVAL_SECTIONS:
                    in_removal_section = True
                elif header.endswith(":") or header.startswith("Transaction Summary"):
                    in_removal_section = False

        return removals

    def _assert_plesk_packages_are_not_removed(self) -> None:
        log_path = self._get_leapp_transaction_log()
        if log_path is None:
            log.warn("No leapp log found, skip the check for Plesk packages scheduled for removal")
            return

        removals = self._get_packages_scheduled_for_removal(log_path)
        critical = sorted({package for package in removals if package in self.CRITICAL_PACKAGES})
        if critical:
            raise PleskPackagesRemovalException(critical)

        other_plesk = sorted({
            package for package in removals
            if package.startswith(self.PLESK_PACKAGE_PREFIXES)
        })
        if other_plesk:
            log.warn(
                "The following Plesk packages have no counterpart on the target OS and will be removed "
                f"by the conversion: {', '.join(other_plesk)}"
            )

        log.info(f"No critical Plesk package is scheduled for removal, {len(removals)} packages will be removed in total")

    def _prepare_action(self) -> action.ActionResult:
        env_vars = os.environ.copy()
        env_vars["LEAPP_OVL_SIZE"] = str(self.leapp_ovl_size)
        if self.allow_unsigned_packages:
            # Leapp only upgrades packages signed by a key it trusts, everything
            # else is treated as third party: left out of the transaction and
            # erased once its dependencies move to the target OS. Unsigned
            # packages cannot be covered by a vendor signature list, so the only
            # way to keep them is to tell leapp to treat every package as signed.
            env_vars["LEAPP_DEVEL_RPMS_ALL_SIGNED"] = "1"
            # Leapp inhibits the conversion when any LEAPP_DEVEL_* variable is set,
            # and points at LEAPP_UNSUPPORTED as the way to proceed anyway. The
            # conversion is then unsupported from the leapp point of view.
            env_vars["LEAPP_UNSUPPORTED"] = "1"

        try:
            util.log_outputs_check_call(["/usr/bin/leapp", "preupgrade"], collect_return_stdout=False, env=env_vars)
        except subprocess.CalledProcessError as e:
            inhibitors = leapp_configs.extract_leapp_report_inhibitors()
            if inhibitors:
                raise LeappPreupgradeRisksPreventedException(inhibitors, e)
            else:
                raise e

        # Leapp does not upgrade packages it considers third party, and erases them
        # when their dependencies are gone. For Plesk that is not recoverable, so
        # stop here while the conversion can still be reverted.
        self._assert_plesk_packages_are_not_removed()

        util.log_outputs_check_call(["/usr/bin/leapp", "upgrade"], collect_return_stdout=False, env=env_vars)
        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        leapp_py3_utility = "/root/tmp_leapp_py3/leapp3"

        # We don't want LEAPP_RESUME_SERVICE will be started in the middle of finishing stage because it
        # could break our normal flow. So we need to prevent systemd from starting it and call directly
        if systemd.is_service_exists(self.LEAPP_RESUME_SERVICE):
            systemd.disable_services([self.LEAPP_RESUME_SERVICE])
            if os.path.exists(leapp_py3_utility):
                util.logged_check_call([leapp_py3_utility, "upgrade", "--resume"])
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        return action.ActionResult()

    def estimate_prepare_time(self) -> int:
        return 40 * 60
