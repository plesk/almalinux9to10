# Copyright 1999- 2025. WebPros International GmbH. All rights reserved.
# vim:ft=python:

include_defs('//product.defs.py')


python_binary(
    name = 'almalinux9to10.pex',
    platform = 'py3',
    build_args = ['--python-shebang', '/usr/bin/env python3'],
    main_module = 'almalinux9to10.main',
    deps = [
        'dist-upgrader//pleskdistup:lib',
        '//almalinux9to10:lib',
    ],
)

genrule(
    name = 'almalinux9to10',
    srcs = [':almalinux9to10.pex'],
    out = 'almalinux9to10',
    cmd = 'cp $(location :almalinux9to10.pex) $OUT && chmod +x $OUT',
)
