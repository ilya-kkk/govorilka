#!/usr/local/bin/python
from __future__ import annotations

import os
import pwd
import sys
from pathlib import Path


APP_USER = "app"
APP_DATA_DIR = Path(os.environ.get("APP_DATA_DIR", "/app/data"))


def chown_tree(path: Path, uid: int, gid: int) -> None:
    os.chown(path, uid, gid)
    for root, dirs, files in os.walk(path):
        for name in dirs:
            os.chown(os.path.join(root, name), uid, gid)
        for name in files:
            os.chown(os.path.join(root, name), uid, gid)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: docker-entrypoint <command> [args...]")

    if os.getuid() == 0:
        user = pwd.getpwnam(APP_USER)
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        chown_tree(APP_DATA_DIR, user.pw_uid, user.pw_gid)
        os.setgid(user.pw_gid)
        os.initgroups(APP_USER, user.pw_gid)
        os.setuid(user.pw_uid)
        os.environ["HOME"] = user.pw_dir

    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
