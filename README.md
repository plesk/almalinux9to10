# Convert a AlmaLinux 9 server with Plesk to AlmaLinux 10

AlmaLinux 9 to 10 conversion tool

## Introduction
This script is the official tool for converting a AlmaLinux 9 server with Plesk to AlmaLinux 10. It uses the [AlmaLinux Elevate tool](https://repo.almalinux.org/elevate/), which is based on the [leapp modernization framework](https://leapp.readthedocs.io/en/latest/). The script includes additional repository and configuration support provided by Plesk.

## Preparation
To avoid downtime and data loss, make sure you have read and understood the following information before using the script:
1. **Back up all your databases** and have the means to restore them. The script uses standard MariaDB and PostgreSQL tools to upgrade the databases, but this does not guarantee that the process will be free of issues.
2. **Ensure that you have a way to restart the server without a direct SSH connection**. The conversion process may get stuck once the server boots into the temporary OS distribution that does not start any network interfaces. You can use a serial port connection to the server to monitor the status of the conversion process in real time, and to reboot the server if necessary.
3. We strongly recommend that you **create a snapshot you can use as a recovery point** in case the conversion process fails.
4. Read the [Known issues](#known-issues) section below for the list of known issues.

## Timing
The conversion process should run between 50 and 80 minutes. **Plesk services, hosted websites, and emails will be unavailable during the entirety of the conversion process**. The conversion process itself consists of three stages:
- Preparation, which takes between 30 and 40 minutes.
- Conversion, which takes between 15 and 30 minutes. During this stage, the server will not be available remotely. You can monitor the progress via a serial port console.
- Finalization, which takes between 5 and 10 minutes.

## Known issues
### Blockers
Do not use the script if any of the following is true:
- **You are running an OS other than AlmaLinux 9**. The script was not tested on other Red Hat Enterprise Linux 9-based distributions. The conversion process may have unexpected results if started on a server not running AlmaLinux 9. So we add checks to avoid any actions on such kinds of servers.
- **Plesk version is more than five releases behind the latest version**. The script is only compatible with the most recent versions of Plesk. It will prevent conversion if Plesk version is outdated.
- **PHP 5.5 and earlier are not supported** in AlmaLinux 10, and will not receive any updates after the conversion. These PHP versions are deprecated and may have security vulnerabilities. So we force to remove this versions before the conversion.
- **Conversion inside containers (like Virtuozzo containers, Docker Containers, etc) are not supported**. 
- **More than one kernel named interfaces (like ethX) are not supported**. Stability of such names are not guaranteed, so leapp prevent the conversion in such cases.
- **MySQL Community is not supported**. AlmaLinux 10 renamed the MySQL packages from 'mysql-server' to 'mysql8.4-server', and the Plesk package for MySQL Community on AlmaLinux 10 still requires the old name. The conversion would remove the database server, so it is refused. Migrate the server to MariaDB before the conversion.
- **XFS filesystems without the 'bigtime' feature are not supported**. AlmaLinux 10 requires it and leapp refuses the conversion otherwise. Filesystems created on AlmaLinux 8 usually lack it, so servers that reached AlmaLinux 9 by an in-place conversion from AlmaLinux 8 are affected. See [XFS filesystem without the bigtime feature](#xfs-filesystem-without-the-bigtime-feature).
- **The EPEL repository is required**. Plesk on AlmaLinux 10 requires 'perl(Digest::SHA1)', which is only provided by the 'perl-Digest-SHA1' package from EPEL.

## Requirements
- Plesk 18.0.71 or later. AlmaLinux 10 packages do not exist for earlier versions.
- Plesk version is not older than five releases back from the latest version
- PHP-7.1, 7.2, and 7.3 is not supported (for now), so conversion will be refused once one of them is installed
- Webalizer web statistics absence. It's not supported in target OS and should be switched to another Plesk-supported stats tool
- AlmaLinux 9.0 or later.
- The EPEL repository is configured and enabled.
- MariaDB as the database server. MySQL Community cannot be upgraded to AlmaLinux 10.
- XFS filesystems provide the 'crc' and 'bigtime' features.
- grub2 is installed
- At least 5 GB of free disk space in /var/lib and 250 MB in /boot.
- At least 3 GB of memory, of which at least 1.5 GB is physical RAM.

## Using the script
To retrieve the latest available version of the tool, please navigate to the "Releases" section. Once there, locate the most recent version of the tool and download the zip archive. The zip archive will contain the almalinux9to10 tool binary.

To prepare the latest version of the tool for use from a command line, please run the following commands:
```shell
> wget https://github.com/plesk/almalinux9to10/releases/download/v1.0.0/almalinux9to10-1.0.0.zip
> unzip almalinux9to10-1.0.0.zip
> chmod 755 almalinux9to10
```

To monitor the conversion process, we recommend using the ['screen' utility](https://www.gnu.org/software/screen/) to run the script in the background. To do so, run the following command:
```shell
> screen -S almalinux9to10
> ./almalinux9to10
```
If you lose your SSH connection to the server, you can reconnect to the screen session by running the following command:
```shell
> screen -r almalinux9to10
```


You can also call almalinux9to10 in the background:
```shell
> ./almalinux9to10 &
```
And monitor its status with the '--status' or '--monitor' flags:
```shell
> ./almalinux9to10 --status
> ./almalinux9to10 --monitor
... live monitor session ...
```


This will start the conversion process. During the process, Plesk services will stop, and hosted websites will not be accessible. At the end of the preparation stage, the server will reboot.
Next, a temporary OS distribution will be used to convert your AlmaLinux 9 system to AlmaLinux 10. This process will take approximately 20 minutes. Once completed, the server will reboot once more. The almalinux9to10 script will then perform the final stages of reconfiguring and restoring Plesk-related services, configurations, and databases. This will take some time, depending on the number of hosted websites.
Once the process is complete, the almalinux9to10 script will reboot the server one last time. After that, Plesk should return to normal operation.
On the next SSH login, you will be greeted with the following message:
```
===============================================================================
Message from the Plesk almalinux9to10 tool:
The server has been converted to AlmaLinux 10.
You can remove this message from the /etc/motd file.
===============================================================================
```

### Conversion stage options
The conversion process consists of two stage options: "start", and "finish":
1. The "start" stage installs and configures ELevate, disables Plesk services and runs ELevate. It then stops Plesk services and reboots the server.
2. The "finish" stage must be called automatically on the first boot of AlmaLinux 10. You can rerun this stage if something goes wrong during the first boot to ensure that the problem is fixed and Plesk is ready to use.

During each phase a conversion plan consisting of stages, which in turn consist of actions, is executed. You can see the general stages in the `--help` output and the detailed plan in the `--show-plan` output.

### Other arguments
- `--fix-deprecated-if-scripts` - Wrap the deprecated `/sbin/if*-local` network scripts into NetworkManager dispatcher scripts. Without the option the conversion is refused while such scripts exist.
- `--migrate-network-config` - Convert the legacy 'ifcfg' network configuration into the NetworkManager 'keyfile' format. AlmaLinux 10 ignores the ifcfg files, so the conversion is refused while they are present. Note that if the files are regenerated on every boot by cloud-init or a provisioning agent, that has to be disabled separately.
- `--allow-unsigned-packages` - Let leapp upgrade the Plesk packages during the conversion even when they are not signed by a trusted key. Without the option unsigned packages are upgraded by the finish stage instead. The option makes leapp treat every third party package on the server as trusted and marks the conversion as unsupported.
- `--upgrade-postgres` - Upgrade all hosted PostgreSQL databases. Create backups of them before using this option.
- `--remove-unknown-perl-modules` - Remove Perl modules installed from CPAN that the tool has no RPM analogue for.
- `--disable-spamassasin-plugins` - Disable additional SpamAssassin plugins during the conversion.
- `--amavis-upgrade-allowed` - Upgrade the Amavis antivirus even when there is not enough RAM for it on the target OS.
- `--allow-raid-devices` - Allow direct RAID devices in /etc/fstab. This may leave the server unbootable after the conversion.
- `--rm-sha1-plesk-packages` - Remove old SHA1 signed Plesk packages before the conversion.
- `--leapp-ovl-size` - Size of the leapp overlay in megabytes, 4096 by default.
- `--keep-leapp-logs` - Keep the leapp logs after the conversion.
- `--allow-old-script-version` - Run the tool without checking GitHub for a newer version.


### Logs
If something goes wrong, read the logs to identify the problem. You can also read the logs to check the status of the finish stage during the first boot.
The almalinux9to10 writes its log to the '/var/log/plesk/almalinux9to10.log' file, as well as to stdout.
The ELevate writes its log to the '/var/log/leapp/leapp-upgrade.log' file. Reports can be found in the '/var/log/leapp/leapp-report.txt' and the '/var/log/leapp/leapp-report.json' files.

### Revert
If the script fails during the the "start" stage before the reboot, you can use the almalinux9to10 script with the '-r' or '--revert' flags to restore Plesk to normal operation. The almalinux9to10 will undo some of the changes it made and restart Plesk services. Once you have resolved the root cause of the failure, you can attempt the conversion again.
Note:
- You cannot use revert to undo the changes after the first reboot triggered by almalinux9to10.
- Revert does not remove Leapp or packages installed by Leapp. Neither does it free persistent storage disk space reserved by Leapp.

### Check the status of the conversion process and monitor its progress
To check the status of the conversion process, use the '--status' flag. You can see the current stage of the conversion process, the elapsed time, and the estimated time until finish.
```shell
> ./almalinux9to10 --status
``` 

To monitor the progress of the conversion process in real time, The conversion process can be monitored in real time using the '--monitor' flag.
```shell
> ./almalinux9to10 --monitor
( stage 3 / action re-installing plesk components  ) 02:26 / 06:18
```

### Special cases

#### Postgresql database before version 10 is installed
By default, the tool does not allow conversion when a PostgreSQL database version prior to 10 is installed. This restriction is in place to warn about the potential loss of data during the PostgreSQL upgrade that will be performed as part of the conversion process.

In such cases, you have two options:

1. Upgrade PostgreSQL to version 10 manually before initiating the conversion.
2. Create a complete backup of the database and force the conversion using the '--upgrade-postgres' flag.

#### XFS filesystem without the bigtime feature
AlmaLinux 10 requires XFS filesystems to provide the 'crc' and 'bigtime' features, and leapp refuses the conversion otherwise. The 'mkfs.xfs' of AlmaLinux 8 does not enable 'bigtime', so filesystems created there lack it, including on servers that reached AlmaLinux 9 by an in-place conversion. Check the filesystem with:
```shell
> xfs_info / | grep -E "crc|bigtime"
```
The 'bigtime' feature can be enabled without recreating the filesystem, but only while it is not mounted. For the root filesystem that means doing it from a rescue boot, or with the disk attached to another server:
```shell
> xfs_admin -O bigtime=1 /dev/<root-device>
```
On a virtual machine the filesystem can also be reached by adding `rd.break=pre-mount` to the kernel command line, which stops the boot before the root filesystem is mounted. Note that 'xfs_admin' is not part of the initramfs by default and has to be added to it first:
```shell
> dracut --force --install "/usr/sbin/xfs_admin /usr/sbin/xfs_db /usr/bin/expr"
```
Filesystems without the 'crc' feature use the old v4 format, which cannot be upgraded at all. Those have to be backed up, recreated with 'mkfs.xfs' and restored before the conversion.

#### Perl modules installed by CPAN
During the conversion process, if the tool detects Perl modules that were installed via CPAN and cannot determine their corresponding RPM packages, it will fail with a warning. This restriction is in place because such modules will not be available after the conversion. This issue often arises because CPAN-installed modules are specifically built for a particular version of Perl. Consequently, when Perl is updated during the conversion process, these module libraries may encounter errors related to undefined symbols.

To prevent this issue, there are steps you can check for RPM package analogues for the modules, remove the CPAN modules, and then reinstall them after the conversion is complete. It is recommended to use RPM packages for reinstallation, although reinstalling the modules via CPAN is also an option.

The almalinux9to10 tool includes a list of RPM mappings for certain modules and can automatically reinstall them. The warning will only raise for modules that mapping to rpm package is unknown by the tool.

If you are confident that you no longer require the modules installed via CPAN, you can forcefully remove them by running the tool with the '--remove-unknown-perl-modules' flag.

## Issue handling
### Leapp unable to handle packages
Leapp may not be able to handle certain installed packages, especially those installed from custom repositories. In this case, the almalinux9to10 will fail while running leapp preupgrade or leapp upgrade. The easiest way to fix this issue is to remove the package(s), and then reinstall them once the conversion is complete.

### Leapp cannot choose which package to install
This issue may occur if unsupported repositories are used. For instance, if an unexpected EPEL repository is enabled on the server, the almalinux9to10 process will fail when running `leapp preupgrade` or `leapp upgrade`. This is due to conflicting packages between the el10 and el9 repositories. The simplest way to resolve this issue is to switch to the standard repositories.

### Temporary OS distribution hangs
This issue may occur, for example, if there is a custom python installation on the server or because of encoding inconsistency. The conversion process will fail while upgrading the temporary OS distribution, and the temporary OS will hang with no notification. To identify the issue, connect to the server using a serial port console and check the status of the conversion process. To fix the issue, reboot the server. Note that an unfinished installation process may result in missing packages and other issues.

### almalinux9to10 finish fails on the first boot
If something goes wrong during the finish stage, you will be informed on the next SSH login with this message:
```
===============================================================================
Message from Plesk almalinux9to10 tool:
Something went wrong during the final stage of AlmaLinux 9 to AlmaLinux 10 conversion
See the /var/log/plesk/almalinux9to10.log file for more information.
You can remove this message from the /etc/motd file.
===============================================================================
```
You can read the almalinux9to10 log to troubleshoot the issue. If the almalinux9to10 finish stage fails for any reason, once you have resolved the root cause of the failure, you can retry by running 'almalinux9to10 --resume'.

### Send feedback
If you got any error, please [create an issue on github](https://github.com/plesk/almalinux9to10/issues). To do generate feedback archive by calling the tool with '-f' or '--prepare-feedback' flags.
```shell
./almalinux9to10 --prepare-feedback
```
Describe your problem and attach the feedback archive to the issue.
