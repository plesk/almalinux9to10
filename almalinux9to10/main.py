#!/usr/bin/python3
# Copyright 1999 - 2026. WebPros International GmbH. All rights reserved.

import sys

from pleskdistup.common import dist

# AlmaLinux 10 is not known to the dist-upgrader distro mapping yet, so register
# it here. This has to happen at import time, before pleskdistup.main is
# imported: pleskdistup.common.src.systemd calls dist.get_distro() at module
# level, which caches the result, and without the target OS registered that
# cached value is an UnknownDistro. The finish phase then refuses to run with
# "Your distribution is not supported yet" once the server is already on
# AlmaLinux 10. Dropping the cached value is safe, because the only import time
# consumer checks deb_based, which is False for both UnknownDistro and AlmaLinux.
dist.register_distro("AlmaLinux", "10", dist.AlmaLinux("10"))
dist.get_distro.cache_clear()

import pleskdistup.main  # noqa: E402
import pleskdistup.registry  # noqa: E402

import almalinux9to10.upgrader  # noqa: E402

if __name__ == "__main__":
    pleskdistup.registry.register_upgrader(almalinux9to10.upgrader.AlmaLinux9to10Factory())
    sys.exit(pleskdistup.main.main())
