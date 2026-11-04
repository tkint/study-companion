"""Study Companion backend."""

import os

# Set from the release tag: the release workflow passes it as the APP_VERSION build arg
# and the image exports it. Local runs and untagged builds report "dev".
__version__ = os.environ.get("APP_VERSION") or "dev"
