"""Domain modules.

Each submodule owns its own `models.py`, `schemas.py`, `validators.py`,
`services.py`, and `router.py` (see docs/ARCHITECTURE.md §10). Modules
communicate with each other only through another module's `services.py`
-- never by importing another module's `models.py` to query/write
directly. This is the seam that would let a module be extracted into its
own service later without a rewrite.

"""
