"""Dashboard server support package (extracted from dashboard_server.py)."""

import os
import site
import sys

# ROS environments often prepend Ubuntu's Python packages. Prefer the user's
# site packages when present so Flask / yaml / rosnode stay importable. Done in
# the package __init__ so it runs before any submodule's heavy imports.
_USER_SITE = site.getusersitepackages()
if _USER_SITE in sys.path:
    sys.path.remove(_USER_SITE)
if os.path.isdir(_USER_SITE):
    sys.path.insert(0, _USER_SITE)
