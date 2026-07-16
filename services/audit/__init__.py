# Marks services/audit as a package root for pytest's importlib mode only, so
# services/audit/tests/conftest.py resolves to the unique module name
# `audit.tests.conftest` rather than colliding with another package's
# `tests.conftest` (e.g. libs/python/emg-audit-pipeline/tests). It is not part
# of the built wheel (hatchling packages src/emg_audit_service) and does not
# affect the importable `emg_audit_service` package.
