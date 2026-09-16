"""Root conftest.

``pytest_plugins`` has to live in the top level conftest since pytest 8, which
is why this file exists next to ``tests/conftest.py``.
"""

pytest_plugins = "pytest_homeassistant_custom_component"
