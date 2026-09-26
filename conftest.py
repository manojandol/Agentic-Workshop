# Empty on purpose: having a conftest.py at the repo root makes pytest add
# the repo root to sys.path, so tests/ can `import schema` (and later
# top-level modules) without a src/ layout or an installed package.
