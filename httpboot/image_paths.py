"""Client image layout, including existing launchers in retained private images."""
import os
from pathlib import Path

CLIENT_LIBRARY = Path('opt/kagnode/httpboot/client')
LEGACY_CLIENT_LIBRARY = Path('usr/local/lib/httpboot')


def public_directory(path):
    """New image-code ancestors stay readable even under a private build umask."""
    missing = []
    while not path.exists():
        missing.append(path)
        path = path.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)


def client_library(root):
    """Move image-local code once; never merge conflicting trees or follow a link.

    This operates on an offline image root, not a running Client or its saves.
    A relative compatibility link keeps retained application launchers working.
    """
    root = Path(root).absolute()
    destination, legacy = root / CLIENT_LIBRARY, root / LEGACY_CLIENT_LIBRARY
    for target in (destination, legacy):
        for parent in target.parents:
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError('Client library parent must not be a symlink: ' + str(parent))
    link = os.path.relpath(destination, legacy.parent)
    if destination.is_symlink():
        raise ValueError('Client library destination must not be a symlink')
    if destination.exists() and not destination.is_dir():
        raise ValueError('Client library destination must be a directory')
    if legacy.is_symlink():
        if os.readlink(legacy) != link or not destination.is_dir():
            raise ValueError('Unexpected legacy Client library link; inspect the image root')
        return destination
    if legacy.exists() and (not legacy.is_dir() or destination.exists()):
        raise ValueError('Conflicting Client library paths; retained files were not changed')
    public_directory(destination.parent)
    if legacy.is_dir():
        legacy.rename(destination)
    else:
        public_directory(destination)
    public_directory(legacy.parent)
    legacy.symlink_to(link, target_is_directory=True)
    return destination
