# Copyright 1999 - 2026. WebPros International GmbH. All rights reserved.

import argparse
import os
import typing

from pleskdistup import actions as common_actions
from pleskdistup.common import action, dist, feedback, files, packages, systemd, util, version
from pleskdistup.phase import Phase
from pleskdistup.messages import REBOOT_WARN_MESSAGE
from pleskdistup.upgrader import DistUpgrader, DistUpgraderFactory, PathType

import almalinux9to10.config
from almalinux9to10 import actions as custom_actions


class AlmaLinux9to10Upgrader(DistUpgrader):
    _distro_from = dist.AlmaLinux("9")
    _distro_to = dist.AlmaLinux("10")

    _pre_reboot_delay = 45

    _elevate_almalinux_rpm_url: str = "https://repo.almalinux.org/elevate/elevate-release-latest-el9.noarch.rpm"
    _leapp_vendors_postgres_repo: str = '/etc/leapp/files/vendors.d/postgresql.repo'
    _sha1_only_packages: typing.List[str] = [
        "libc-client",
        "plesk-php56", "plesk-php70", "plesk-php74", "plesk-php80",
    ]


    def __init__(self):
        super().__init__()

        self.fix_deprecated_if_scripts = False
        self.migrate_network_config = False
        self.allow_unsigned_packages = False
        self.upgrade_postgres_allowed = False
        self.remove_unknown_perl_modules = False
        self.disable_spamassasin_plugins = False
        self.amavis_upgrade_allowed = False
        self.leapp_ovl_size = 4096
        self.allow_raid_devices = False
        self.rm_sha1_plesk_packages = False
        self.remove_leapp_logs = False
        self.allow_old_script_version = False
        self.skip_space_checks = False

    def __repr__(self) -> str:
        attrs = ", ".join(f"{k}={getattr(self, k)!r}" for k in (
            "_distro_from", "_distro_to",
        ))
        return f"{self.__class__.__name__}({attrs})"

    def __str__(self) -> str:
        return f"{self.__class__.__name__}"

    @classmethod
    def supports(
        cls,
        from_system: typing.Optional[dist.Distro] = None,
        to_system: typing.Optional[dist.Distro] = None
    ) -> bool:
        return (
            (from_system is None or cls._distro_from == from_system)
            and (to_system is None or cls._distro_to == to_system)
        )

    @property
    def upgrader_name(self) -> str:
        return "Plesk::AlmaLinux9to10Upgrader"

    @property
    def upgrader_version(self) -> str:
        if almalinux9to10.config.version:
            return almalinux9to10.config.version + "-" + almalinux9to10.config.revision[:8]
        return almalinux9to10.config.revision

    @property
    def issues_url(self) -> str:
        return "https://github.com/plesk/almalinux9to10/issues"

    def prepare_feedback(
        self,
        feed: feedback.Feedback,
    ) -> feedback.Feedback:

        feed.collect_actions += [
            feedback.collect_installed_packages_yum,
            feedback.collect_plesk_version,
            feedback.collect_kernel_modules,
        ]

        feed.attached_files += [
            "/etc/fstab",
            "/etc/grub2.cfg",
            "/etc/leapp/files/repomap.csv",
            "/etc/leapp/files/pes-events.json",
            "/etc/leapp/files/leapp_upgrade_repositories.repo",
            "/etc/named.conf",
            "/var/named/chroot/etc/named.conf",
            "/var/named/chroot/etc/named-user-options.conf",
            "/var/log/leapp/leapp-report.txt",
            "/var/log/leapp/leapp-preupgrade.log",
            "/var/log/leapp/leapp-upgrade.log",
        ]

        for grub_directory in ("/etc/grub.d", "/boot/grub", "/boot/grub2"):
            feed.attached_files += files.find_files_case_insensitive(grub_directory, ["*"])

        for repofile in files.find_files_case_insensitive("/etc/yum.repos.d", ["*.repo*"]):
            feed.attached_files.append(repofile)

        for gpgfile in files.find_files_case_insensitive("/etc/leapp/files/vendors.d/rpm-gpg", ["*"]):
            feed.attached_files.append(gpgfile)

        for gpgfile in files.find_files_case_insensitive("/etc/leapp/repos.d/system_upgrade/common/files/rpm-gpg", ["*"], recursive=True):
            feed.attached_files.append(gpgfile)

        return feed

    def construct_actions(
        self,
        upgrader_bin_path: PathType,
        options: typing.Any,
        phase: Phase
    ) -> typing.Dict[str, typing.List[action.ActiveAction]]:
        new_os = str(self._distro_to)

        actions_map: typing.Dict[str, typing.List[action.ActiveAction]] = {
            "Status informing": [
                common_actions.HandleConversionStatus(options.status_flag_path, options.completion_flag_path),
                common_actions.AddFinishSshLoginMessage(new_os),  # Executed at the finish phase only
                common_actions.AddInProgressSshLoginMessage(new_os),
            ],
            "Leapp installation": [
                common_actions.RemoveLeappReposDisablement(),
                common_actions.LeappInstallation(
                    self._elevate_almalinux_rpm_url,
                    [
                        "leapp-0.20.0-2.el9",
                        "leapp-data-almalinux-0.11-10.el9.20251222",
                        "leapp-deps-0.20.0-2.el9",
                        "leapp-upgrade-el9toel10-0.24.0-1.el9.elevate.5",
                        "leapp-upgrade-el9toel10-deps-0.24.0-1.el9.elevate.5",
                        "python3-leapp-0.20.0-2.el9",
                    ],
                    remove_logs_on_finish=self.remove_leapp_logs
                ),
            ],
            "Prepare finishing systemd service": [
                common_actions.AddUpgradeSystemdService(
                    os.path.abspath(upgrader_bin_path),
                    options,
                    service_name = common_actions.DEFAULT_RESUME_SERVICE_NAME,
                    remove_service_in_post = False, # will be removed before reboot
                ),
                common_actions.StopStartServices(["logrotate.timer"], disable_on_prep=False),
            ],
            "Prepare configurations": [
                common_actions.RepairPleskInstallation(),  # Executed at the finish phase only
                common_actions.RevertChangesInGrub(),
                custom_actions.RemoveOldPostgresRepoDefs(self._leapp_vendors_postgres_repo),
                custom_actions.PrepareLeappConfigurationBackup(),
                custom_actions.RemoveOldMigratorThirdparty(),
                custom_actions.FetchKernelCareGPGKey(),
                custom_actions.FetchPleskGPGKey(),
                custom_actions.FetchImunifyGPGKey(),
                custom_actions.ProvidePleskGPGKeyFile(),
                custom_actions.PleskMainRepoTemporary(),
                custom_actions.FetchEpelGPGKeyForTarget(),
                custom_actions.ProvidePleskVendorSignatures(),
                custom_actions.LeappReposConfiguration(),
                custom_actions.AdoptKolabRepositories(),
                custom_actions.AdoptAtomicRepositories(),
                custom_actions.FixupImunify(),
                common_actions.UpdatePlesk(),
                custom_actions.PostgresReinstallModernPackage(),
                common_actions.FixNamedConfig(),
                common_actions.DisablePleskSshBanner(),
                common_actions.SetMinDovecotDhParamSize(dhparam_size=2048),
                common_actions.RestoreDovecotConfiguration(options.state_dir),
                common_actions.RestoreRoundcubeConfiguration(options.state_dir),
                common_actions.RecreateAwstatsConfigurationFiles(),
                common_actions.UninstallTuxcareEls(),
                common_actions.UninstallExtension("tuxcare-php"),
                common_actions.PreserveMariadbConfig(),
                common_actions.SubstituteSshPermitRootLoginConfigured(),
                custom_actions.UseSystemResolveForLeappContainer(),
            ],
            "Handle plesk related services": [
                custom_actions.PostStartProftpd(),
                common_actions.DisablePleskRelatedServicesDuringUpgrade(),
                common_actions.DisableServiceDuringUpgrade("mailman.service"),
                common_actions.HandlePleskFirewallService(),
            ],
            "Handle packages and services": [
                common_actions.RemovePleskComponents(
                    ["webalizer"], options.state_dir, "rm webalizer component",
                ),
                custom_actions.FixOsVendorPhpFpmConfiguration(),
                common_actions.RebundleRubyApplications(),
                custom_actions.ReinstallPhpmyadminPleskComponents(),
                custom_actions.ReinstallRoundcubePleskComponents(),
                custom_actions.ReinstallConflictPackages(options.state_dir),
                custom_actions.ReinstallPerlCpanModules(options.state_dir),
                common_actions.DisableSuspiciousKernelModules(),
                common_actions.HandleUpdatedSpamassassinConfig(),
                common_actions.DisableSelinuxDuringUpgrade(),
                common_actions.RestoreMissingNginx(),
                common_actions.ReinstallAmavisAntivirus(),
                custom_actions.HandleInternetxRepository(),
                # Runs in the finish phase, so the extensions are updated to the
                # builds made for the target OS. The same set the Debian and
                # Ubuntu converters update.
                custom_actions.UpdatePleskExtensionsAfterConversion([
                    "panel-migrator", "site-import", "docker", "grafana", "ruby", "kolab",
                ]),
            ],
            "First plesk start": [
                common_actions.StartPleskBasicServices(),
            ],
            # Placed after "First plesk start" on purpose: the finish phase walks
            # the stages in reverse order, so the policy is loaded before anything
            # tries to start Apache.
            "Restore SELinux policy": [
                custom_actions.LoadPleskSelinuxPolicy(),
                custom_actions.FixPostfixDatabaseType(),
            ],
            "Remove conflicting packages": [
                custom_actions.RemovingPleskConflictPackages(),
                custom_actions.RemovePleskOutdatedPackages(),
            ],
            "Update databases": [
                # The same settings the Debian and Ubuntu converters apply.
                # MariaDB 10.11 on AlmaLinux 10 refuses to bind the IPv4 mapped
                # IPv6 address Plesk configures, and innodb_fast_shutdown=0 makes
                # MariaDB flush everything before the conversion, so the data
                # directory is clean for the newer server.
                common_actions.ConfigureMariadb(
                    {
                        "mysqld.bind-address": {
                            "prepare": common_actions.ConfigValueReplacer(
                                new_value="127.0.0.1", old_value="::ffff:127.0.0.1",
                            ),
                            "post": common_actions.ConfigValueReplacer(
                                new_value="127.0.0.1", old_value="::ffff:127.0.0.1",
                            ),
                            # No revert on purpose. The Ubuntu converter restores the
                            # IPv4 mapped address unconditionally, which writes a value
                            # the server never had when bind-address was already plain
                            # IPv4, conflicts with the other MariaDB configuration files
                            # and leaves MariaDB unable to start (PAUX-7251). Plain IPv4
                            # is valid on AlmaLinux 9 as well, so there is nothing that
                            # has to be restored.
                        },
                        "mysqld.innodb_fast_shutdown": {
                            "prepare": common_actions.ConfigValueReplacer(new_value="0", old_value=None),
                            # innodb_fast_shutdown is only needed while the data
                            # directory is handed over to the newer server, so it has
                            # to be dropped again on both of the terminating stages.
                            # Leaving it behind makes every later MariaDB shutdown do a
                            # full purge and merge of the change buffer.
                            "post": common_actions.ConfigValueReplacer(new_value=None, old_value="0"),
                            "revert": common_actions.ConfigValueReplacer(new_value=None, old_value="0"),
                        },
                    },
                    conf_file="/etc/my.cnf",
                ),
                custom_actions.UpdateModernMariadb(),
                custom_actions.AddMysqlConnector(),
            ],
            "Repositories handling": [
                custom_actions.SetRPMCryptoPolicy(self._sha1_only_packages, "LEGACY"),
                custom_actions.AdoptRepositories(),
                custom_actions.PostEnableRepos(["crb"]),
                # perl-Digest-SHA1 is declared removed without a replacement by the leapp
                # package events, but el10 plesk-core requires perl(Digest::SHA1) and EPEL 10
                # provides the package. Leaving the event in place makes plesk-core
                # uninstallable, so leapp erases the el9 one as a dependent package and the
                # removal branch of its %preun scriptlet tries to drop the Plesk databases.
                custom_actions.DisablePesEventsRemovePackages([
                    "libidn",
                    # Declared removed in el10 by the leapp package events, but the
                    # packages do exist for AlmaLinux 10 (mostly in EPEL, which the
                    # conversion enables) and a working Plesk installation on
                    # AlmaLinux 10 has them. Letting leapp erase them makes the el10
                    # Plesk packages uninstallable, so dnf drops the whole Plesk
                    # stack as dependent packages instead of upgrading it.
                    "perl-Digest-SHA1",
                    "xmlrpc-c",
                    "libdb",
                    "enchant",
                    "libstemmer",
                    "libwmf-lite",
                    "LibRaw",
                    "mod_security",
                    # Provides libmilter.so.1.0, which plesk-mail-pc-driver links
                    # against. Removing it drops the Plesk mail driver, and Plesk
                    # then stops recognizing Postfix as an installed component.
                    "sendmail-milter",
                ]),
            ],
            "Do convert": [
                custom_actions.DisableBaseRepoUpdatesRepository(),
                custom_actions.RemovePleskBaseRepository(),
                custom_actions.DoAlmaLinux9to10Convert(
                    leapp_ovl_size=self.leapp_ovl_size,
                    allow_unsigned_packages=self.allow_unsigned_packages,
                ),
            ],
            "Resume": [
                common_actions.RestoreInProgressSshLoginMessage(new_os),
            ],
            "Pause before reboot": [
            ],
            "Reboot": [
                common_actions.Reboot(
                    prepare_next_phase=Phase.FINISH,
                    post_reboot=action.RebootType.AFTER_LAST_STAGE,
                    name="reboot and perform finishing actions",
                    do_before_post_reboot=lambda: \
                        systemd.remove_systemd_service(common_actions.DEFAULT_RESUME_SERVICE_NAME)
                )
            ]
        }

        if self.fix_deprecated_if_scripts:
            actions_map = util.merge_dicts_of_lists(actions_map, {
                "Prepare configurations": [
                    custom_actions.FixDeprecatedIFScripts(),
                ]
            })

        if self.migrate_network_config:
            actions_map = util.merge_dicts_of_lists(actions_map, {
                "Prepare configurations": [
                    custom_actions.MigrateLegacyNetworkConfiguration(),
                ]
            })

        if self.rm_sha1_plesk_packages:
            actions_map = util.merge_dicts_of_lists(actions_map, {
                "Handle packages and services": [
                    custom_actions.RemovePleskSHA1Packages(),
                ]
            })

        if not options.no_reboot:
            actions_map = util.merge_dicts_of_lists(actions_map, {
                "Pause before reboot": [
                    common_actions.PreRebootPause(
                        REBOOT_WARN_MESSAGE.format(delay=self._pre_reboot_delay, util_name="almalinux9to10"),
                        self._pre_reboot_delay
                    ),
                ]
            })

        if self.upgrade_postgres_allowed:
            actions_map = util.merge_dicts_of_lists(actions_map, {
                "Prepare configurations": [
                    custom_actions.PostgresDatabasesUpdate(),
                ]
            })

        return actions_map

    def get_check_actions(
        self,
        options: typing.Any,
        phase: Phase
    ) -> typing.List[action.CheckAction]:
        if phase is Phase.FINISH:
            return [custom_actions.AssertDistroIsAlmaLinux10()]

        FIRST_SUPPORTED_BY_ALMA_10_PHP_VERSION = "5.6"
        ALMALINUX10_AMAVIS_REQUIRED_RAM = int(1.5 * 1024 * 1024 * 1024)
        # Observed peak: 'dnf' inside the leapp container reached 1.4 GB on a Plesk
        # server and was OOM killed on a host with 1.7 GB of RAM and no swap.
        LEAPP_REQUIRED_MEMORY = 3 * 1024 * 1024 * 1024
        # From our experience it's better to have at least 5GB as the required minimum space to store packages,
        # however when more space is required we should check exactly what was requested.
        # Leapp_ovl_size in Mbs so we have to multiply
        REQUIRED_MINUMUM_SPACE_FOR_OVERLAY = max(5 * 1024 * 1024 * 1024, self.leapp_ovl_size * 1024 * 1024)

        checks = [
            common_actions.AssertPleskVersionIsAvailable(),
            # AlmaLinux 10 packages first appeared in Plesk 18.0.71, there is
            # nothing to convert to on older versions.
            common_actions.AssertMinPleskVersion("18.0.71"),
            common_actions.AssertPleskInstallerNotInProgress(),
            common_actions.AssertMinPhpVersionInstalled(FIRST_SUPPORTED_BY_ALMA_10_PHP_VERSION),
            common_actions.AssertMinPhpVersionUsedByWebsites(FIRST_SUPPORTED_BY_ALMA_10_PHP_VERSION),
            common_actions.AssertMinPhpVersionUsedByCron(FIRST_SUPPORTED_BY_ALMA_10_PHP_VERSION),
            common_actions.AssertOsVendorPhpUsedByWebsites(FIRST_SUPPORTED_BY_ALMA_10_PHP_VERSION),
            common_actions.AssertGrub2Installed(),
            custom_actions.AssertNoMoreThenOneKernelNamedNIC(),
            custom_actions.AssertRedHatKernelInstalled(),
            custom_actions.AssertCgroupsV2Enabled(),
            custom_actions.AssertEpelRepositoryAvailable(),
            custom_actions.AssertNoPackageExcludes(),
            custom_actions.AssertEnoughMemoryForLeapp(LEAPP_REQUIRED_MEMORY),
            custom_actions.AssertXfsFilesystemsSupported(),
            custom_actions.AssertLastInstalledKernelInUse(),
            common_actions.AssertLocalRepositoryNotPresent(file_list = [
                    file for file in files.find_files_case_insensitive("/etc/yum.repos.d", "*.repo")
                    if os.path.basename(file) != "AlmaLinux-Media.repo"
                 ]),
            common_actions.AssertIPRepositoryNotPresent(),
            custom_actions.CheckNMUnreachableDevices(),
            common_actions.AssertNoRepositoryDuplicates(),
            common_actions.AssertPackageIsNotInstalled("plesk-php71",
                                                       "PHP-7.1 is not supported"),
            common_actions.AssertPackageIsNotInstalled("plesk-php72",
                                                       "PHP-7.2 is not supported"),
            common_actions.AssertPackageIsNotInstalled("plesk-php73",
                                                       "PHP-7.3 is not supported"),
            common_actions.AssertPackageIsNotInstalled("psa-qmail",
                                                       "QMail is not supported on AlmaLinux 10 - consider switching to Postfix before conversion"),
            custom_actions.AssertStatsToolNotUsed('webalizer'),
            common_actions.AssertConfigurationConflictsResolved(["/etc/my.cnf"]),
            custom_actions.AssertMysqlCommunityNotInstalled(),
            custom_actions.AssertMariadbRepoAvailable(),
            common_actions.AssertMariadbRepoEnabled(
                custom_actions.MARIADB_VERSION_ON_ALMA,
                custom_actions.KNOWN_MARIADB_REPO_FILES,
            ),
            custom_actions.AssertModernPostgresRepositoryFilePresent(),
            common_actions.AssertNotInContainer(),
            custom_actions.AssertPackagesUpToDate(),
            custom_actions.AssertNoOutdatedLetsEncryptExtRepository(),
            custom_actions.AssertPleskRepositoriesNotNoneLink(),
            common_actions.AssertNoAbsoluteLinksInRoot(),
            custom_actions.CheckSourcePointsToArchiveURL(),
            common_actions.AssertNoMoreThenOneKernelDevelInstalled(),
            common_actions.AssertEnoughRamForAmavis(ALMALINUX10_AMAVIS_REQUIRED_RAM, self.amavis_upgrade_allowed),
            common_actions.AssertSshPermitRootLoginConfigured(skip_known_substitudes=True),
            common_actions.AssertFstabOrderingIsFine(),
            common_actions.AssertFstabHasDirectRaidDevices(self.allow_raid_devices),
            common_actions.AssertFstabHasNoDuplicates(),
            common_actions.AssertPackageAvailable(
                "dnf",
                name="asserting dnf package available",
                recommendation="""The dnf package is required for Leapp to function properly.
\tHint: You can install it using the AlmaLinux-9 BaseOS repository with the following base URL:
\t\t'baseurl=https://repo.almalinux.org/almalinux/9/BaseOS/x86_64/os/'"""
            ),
        ]

        if not self.fix_deprecated_if_scripts:
            checks.append(custom_actions.CheckDeprecatedIFScripts())
        if not self.migrate_network_config:
            checks.append(custom_actions.AssertNoLegacyNetworkConfiguration())
        if not self.upgrade_postgres_allowed:
            checks.append(custom_actions.AssertOutdatedPostgresNotInstalled())
        else:
            checks.append(custom_actions.AssertPostgresLocaleMatchesSystemOne())
        if not self.remove_unknown_perl_modules:
            checks.append(custom_actions.AssertThereIsNoUnknownPerlCpanModules())
        if not self.disable_spamassasin_plugins:
            checks.append(common_actions.AssertSpamassassinAdditionalPluginsDisabled())
        if not self.allow_old_script_version and almalinux9to10.config.version:
            checks.append(common_actions.AssertScriptVersionUpToDate("https://github.com/plesk/almalinux9to10", "almalinux9to10", version.DistupgradeToolVersion(almalinux9to10.config.version)))
        if not any(packages.is_package_installed(name) for name in self._sha1_only_packages):
            checks.append(
                custom_actions.AssertNoOldRPMSignatures(not self.rm_sha1_plesk_packages))
        if not self.skip_space_checks:
            checks.append(
                common_actions.AssertAvailableSpaceForLocation("/var/lib", REQUIRED_MINUMUM_SPACE_FOR_OVERLAY),
            )
            checks.append(
                # Leapp's own checkbootavailspace inhibitor requires 100 MiB, which is
                # optimistic: it also has to fit the upgrade initramfs and the target OS
                # kernel. 250M keeps a real margin and still fits the 459M /boot partition
                # the standard AlmaLinux 9 VM provisioning creates. The 500M used by the
                # AlmaLinux 8 to 9 tool is unsatisfiable on that layout.
                common_actions.AssertAvailableSpaceForLocation("/boot", 250 * 1024 * 1024),
            )

        return checks

    def parse_args(self, args: typing.Sequence[str]) -> None:
        DESC_MESSAGE = f"""Use this upgrader to convert {self._distro_from} server with Plesk to {self._distro_to}.
The process consists of the following general stages:

- Preparation (about 20 minutes) - The Leapp utility is installed and configured.
   The OS is prepared for the conversion. The Leapp utility is then called to
   create a temporary OS distribution.
- Conversion (about 20 minutes) - The conversion takes place. During this stage,
   you cannot connect to the server via SSH.
- Finalization (about 5 minutes) - The server is returned to normal operation.

To see the detailed plan, run the utility with the --show-plan option.

For assistance, submit an issue here {self.issues_url}
and attach the feedback archive generated with --prepare-feedback or at least
the log file.
"""
        parser = argparse.ArgumentParser(
            usage=argparse.SUPPRESS,
            description=DESC_MESSAGE,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            add_help=False,
        )
        parser.add_argument(
            "-h", "--help", action="help", default=argparse.SUPPRESS,
            help=argparse.SUPPRESS
        )
        parser.add_argument(
            "--fix-deprecated-if-scripts", action="store_true", dest="fix_deprecated_if_scripts", default=False,
            help="Fix deprecated custom network scripts. Custom network scripts in /sbin/if*-local are deprecated and may not work properly on AlmaLinux 10. By enabling this option, the utility will create wrapper scripts that will call the original scripts if they exist and are executable."
        )
        parser.add_argument(
            "--allow-unsigned-packages", action="store_true", dest="allow_unsigned_packages", default=False,
            help="Let leapp upgrade the Plesk packages during the conversion even when they are not signed by a trusted key. "
                 "Without this option unsigned packages are upgraded by the finish stage instead, which is how the AlmaLinux 8 to 9 conversion behaves. "
                 "The option makes leapp treat every third party package on the server as trusted and marks the conversion as unsupported, so only use it when that is acceptable."
        )
        parser.add_argument(
            "--migrate-network-config", action="store_true", dest="migrate_network_config", default=False,
            help="Convert legacy 'ifcfg' network configuration into the NetworkManager 'keyfile' format. "
                 "AlmaLinux 10 ignores the ifcfg files, so the conversion is refused while they are present. "
                 "Note that if the files are generated on every boot by cloud-init, they have to be disabled there as well."
        )
        parser.add_argument(
            "--upgrade-postgres", action="store_true", dest="upgrade_postgres_allowed", default=False,
            help="Upgrade all hosted PostgreSQL databases. To avoid data loss, create backups of all "
                 "hosted PostgreSQL databases before calling this option."
        )
        parser.add_argument(
            "--remove-unknown-perl-modules", action="store_true",
            dest="remove_unknown_perl_modules", default=False,
            help="Allow to remove unknown perl modules installed from CPAN. In this case all modules installed "
                 "by CPAN will be removed. Note that it could lead to some issues with perl scripts"
        )
        parser.add_argument(
            "--disable-spamassasin-plugins", action="store_true",
            dest="disable_spamassasin_plugins", default=False,
            help="Disable additional plugins in spamassasin configuration during the conversion."
        )
        parser.add_argument("--leapp-ovl-size", type=int, dest="leapp_ovl_size", default=4096,
                            help="Specify the overlay size for leapp in megabytes.")
        parser.add_argument("--amavis-upgrade-allowed", action="store_true", dest="amavis_upgrade_allowed", default=False,
                            help="Allow to upgrade amavis antivirus even if there is not enough RAM available.")
        parser.add_argument("--allow-raid-devices", action="store_true", dest="allow_raid_devices", default=False,
                            help="Allow to have direct RAID devices in /etc/fstab. This could lead to unbootable system after the conversion so use the option on your own risk.")
        parser.add_argument("--keep-leapp-logs", action="store_false", dest="remove_leapp_logs",
                            help="Don't remove leapp logs after the conversion. By default, the logs are removed after the conversion.")
        parser.add_argument("--allow-old-script-version", action="store_true", dest="allow_old_script_version", default=False,
                            help="Allow to run the script with an old version. By default, the script checks for a new version on GitHub and does not allow to run with an old one.")
        parser.add_argument(
            "--rm-sha1-plesk-packages", action="store_true",
            help="remove SHA1 signed old Plesk packages before conversion."
        )
        parser.add_argument(
            "--skip-space-checks", action="store_true",
            help=argparse.SUPPRESS,
        )
        parser.set_defaults(remove_leapp_logs=False)
        options = parser.parse_args(args)

        self.upgrade_postgres_allowed = options.upgrade_postgres_allowed
        self.remove_unknown_perl_modules = options.remove_unknown_perl_modules
        self.disable_spamassasin_plugins = options.disable_spamassasin_plugins
        self.amavis_upgrade_allowed = options.amavis_upgrade_allowed
        self.leapp_ovl_size = options.leapp_ovl_size
        self.allow_raid_devices = options.allow_raid_devices
        self.rm_sha1_plesk_packages = options.rm_sha1_plesk_packages
        self.remove_leapp_logs = options.remove_leapp_logs
        self.allow_old_script_version = options.allow_old_script_version
        self.fix_deprecated_if_scripts = options.fix_deprecated_if_scripts
        self.migrate_network_config = options.migrate_network_config
        self.allow_unsigned_packages = options.allow_unsigned_packages
        self.skip_space_checks = options.skip_space_checks


class AlmaLinux9to10Factory(DistUpgraderFactory):
    def __init__(self):
        super().__init__()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(upgrader_name={self.upgrader_name})"

    def __str__(self) -> str:
        return f"{self.__class__.__name__} (creates {self.upgrader_name})"

    def supports(
        self,
        from_system: typing.Optional[dist.Distro] = None,
        to_system: typing.Optional[dist.Distro] = None
    ) -> bool:
        return AlmaLinux9to10Upgrader.supports(from_system, to_system)

    @property
    def upgrader_name(self) -> str:
        return "Plesk::AlmaLinux9to10Upgrader"

    def create_upgrader(self, *args, **kwargs) -> DistUpgrader:
        return AlmaLinux9to10Upgrader(*args, **kwargs)
