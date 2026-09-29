# Copyright 1999 - 2026. WebPros International GmbH. All rights reserved.

import os
import re
import subprocess
import typing

from pleskdistup.common import action, files, log, util


class FixPostfixDatabaseType(action.ActiveAction):
    """Switch the Postfix lookup tables from the 'hash' to the 'lmdb' type.

    The 'hash' map type is backed by Berkeley DB, which is not part of
    AlmaLinux 10 anymore: there is no postfix-hash package for it, only
    postfix-lmdb. Plesk writes the map type explicitly into its Postfix
    configuration, so the configuration of the source OS keeps referring to
    'hash:' maps after the conversion. Postfix then fails to open its lookup
    tables ('unsupported map type: hash'), which also fails the mail part of
    'plesk repair installation'. A Plesk installation made on AlmaLinux 10 uses
    'lmdb:' and compatibility level 3.8, so the conversion adopts the same.
    """

    POSTFIX_CONFIG_FILES: typing.List[str] = ["/etc/postfix/main.cf", "/etc/postfix/master.cf"]
    POSTCONF_BIN = "/usr/sbin/postconf"
    POSTALIAS_BIN = "/usr/sbin/postalias"
    POSTMAP_BIN = "/usr/sbin/postmap"
    TARGET_COMPATIBILITY_LEVEL = "3.8"
    # 'hash:' only where it introduces a lookup table, not inside a longer word
    HASH_MAP_REGEX = re.compile(r"(?<![A-Za-z0-9_.-])hash:")
    LMDB_MAP_REGEX = re.compile(r"(?<![A-Za-z0-9_.-])lmdb:(\S+)")

    def __init__(self) -> None:
        self.name = "fix the Postfix lookup table type"

    def _get_configs_with_hash_maps(self) -> typing.List[str]:
        affected = []
        for config in self.POSTFIX_CONFIG_FILES:
            if not os.path.exists(config):
                continue
            try:
                with open(config) as conf:
                    if any(self.HASH_MAP_REGEX.search(line) for line in conf if not line.lstrip().startswith("#")):
                        affected.append(config)
            except OSError as ex:
                log.warn(f"Unable to read the Postfix configuration {config!r}: {ex}")

        return affected

    def _is_required(self) -> bool:
        return os.path.exists(self.POSTCONF_BIN) and bool(self._get_configs_with_hash_maps())

    def _fix_config(self, config: str) -> None:
        with open(config) as conf:
            lines = conf.readlines()

        fixed = [
            line if line.lstrip().startswith("#") else self.HASH_MAP_REGEX.sub("lmdb:", line)
            for line in lines
        ]
        if fixed == lines:
            return

        log.info(f"Replacing the 'hash' lookup tables with 'lmdb' ones in {config!r}")
        files.backup_file(config)
        with open(config, "w") as conf:
            conf.writelines(fixed)

    def _get_map_files(self) -> typing.List[str]:
        maps: typing.List[str] = []
        for config in self.POSTFIX_CONFIG_FILES:
            if not os.path.exists(config):
                continue
            with open(config) as conf:
                for line in conf:
                    if line.lstrip().startswith("#"):
                        continue
                    for path in self.LMDB_MAP_REGEX.findall(line):
                        path = path.rstrip(",")
                        if path.startswith("/") and path not in maps and os.path.exists(path):
                            maps.append(path)

        return maps

    def _rebuild_maps(self) -> None:
        # The existing .db files are Berkeley DB ones and are of no use anymore,
        # the .lmdb counterparts have to be generated from the plain text sources.
        for path in self._get_map_files():
            tool = self.POSTALIAS_BIN if os.path.basename(path) == "aliases" else self.POSTMAP_BIN
            if not os.path.exists(tool):
                continue
            try:
                util.logged_check_call([tool, path])
            except subprocess.CalledProcessError as ex:
                # Plesk regenerates its own tables during the repair that follows
                log.warn(f"Unable to rebuild the Postfix lookup table {path!r}: {ex}")

    def _prepare_action(self) -> action.ActionResult:
        return action.ActionResult()

    def _post_action(self) -> action.ActionResult:
        for config in self._get_configs_with_hash_maps():
            self._fix_config(config)

        util.logged_check_call([
            self.POSTCONF_BIN, "-e",
            f"compatibility_level={self.TARGET_COMPATIBILITY_LEVEL}",
            "default_database_type=lmdb",
        ])
        self._rebuild_maps()
        return action.ActionResult()

    def _revert_action(self) -> action.ActionResult:
        for config in self.POSTFIX_CONFIG_FILES:
            files.restore_file_from_backup(config)
        return action.ActionResult()

    def estimate_post_time(self) -> int:
        return 10
