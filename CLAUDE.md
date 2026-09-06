# Lyngdorf Project

Python library to control Lyngdorf A/V processors (MP-60, TDAI-1120).

## Setup

- Python 3.11+
- Poetry for dependency management
- Virtual environment: `.venv`

## Commands

```bash
poetry install          # Install dependencies
poetry run pytest       # Run tests
poetry run black .      # Format code
```

## Project Structure

- `lyngdorf/` - Main package
- `tests/` - Pytest tests

## Dependencies

- `aiohttp` - the only runtime dependency. All device HTTP (the streaming
  module's `:8080` JSON API) goes through it; the `:84` control protocol
  is raw asyncio. `attrs` was removed in 2.0 - use `dataclasses`.

## Testing Requirements

**IMPORTANT**: All features must have corresponding unit tests before being committed.

### Test Coverage Guidelines

1. **New Features**: Every new feature, method, or capability MUST have unit tests
   - Public API methods require tests
   - Model-specific configurations require tests
   - Capability is **structural**, not a predicate: a model without a
     feature has no object for it (`player is None`, `zone_b is None`,
     `Trim.X not in trims`). The `has_*_feature()` methods were deleted
     in 2.1. Test the presence or absence of the object, and assert it
     against `ModelConfig` rather than hardcoding a model list.

2. **Test Patterns**: Follow existing patterns in the suite - `tests/receiver_test.py`
   for receiver state and callbacks, `tests/components_test.py` for Zone B
   and Remote, `tests/controls_test.py` for the numeric controls
   - Group related tests in test classes
   - Use descriptive test names that explain what is being tested
   - Test both positive and negative cases

3. **Model Configuration Tests**: When adding new model configs or capabilities
   - Test that all models return correct values
   - Test that feature flags are set correctly (MP series vs TDAI series)
   - Test command lookups and protocol mappings

4. **Running Tests**:
   ```bash
   poetry run pytest              # Run all tests
   poetry run pytest -v           # Verbose output
   poetry run pytest tests/       # Run specific test directory
   ```

5. **Quality Checks**: All checks must pass before committing
   ```bash
   poetry run mypy lyngdorf/      # Type checking
   poetry run ruff check .        # Linting
   poetry run black --check .     # Code formatting check
   ```

### Examples

- `tests/controls_test.py` - `TestVolumeFactory` for per-model ranges
  asserted against `ModelConfig`, and for the anchors that stop a config
  bug satisfying its own test
- `tests/components_test.py` - `TestZoneBFactory` for structural
  capability (parametrise over the models that have the feature; do not
  enter and skip)
- `tests/discovery_test.py` - `TestLookupModel` for model resolution
- `tests/session_leak_test.py` - for anything touching the connect /
  disconnect lifecycle

### Hardware claims

Anything asserted about a device belongs in `docs/<model>.md` with how it
was established. Distinguish **measured** from **manual-derived**: the P
family has now twice been found non-uniform where the manual implied
otherwise, so a measurement on one model is not evidence about its
siblings. See `docs/p-series.md` and `docs/firmware-provenance.md`.

## Release Process

Two separate workflows, two separate triggers:

- `.github/workflows/run-tests.yml` - runs on every push to `main` (tests, mypy, ruff, black).
- `.github/workflows/publish.yml` - runs on push of a `v*` **tag** only. Publishes to PyPI via OIDC Trusted Publishing (`pypa/gh-action-pypi-publish`, generates a PEP 740 attestation) - no static API token. Skips the build/publish steps if that version already exists on PyPI. Also verifies the tag matches `pyproject.toml`'s version and fails loudly if they disagree.

**A tag is the only thing that publishes.** Bumping `pyproject.toml` and pushing to `main` does *not* publish by itself - it only runs tests. This is deliberate: earlier the trigger was "push to `main` touching `pyproject.toml`", which meant a commit landing *after* the version-bump commit (but before a release was cut) silently never got published under that version. Tag-per-release closes that gap, since cutting the release is always the last step anyway.

To cut a release:

1. Bump `version` in `pyproject.toml`, commit, push to `main`.
2. Wait for `Run tests` to go green on that commit.
3. `gh release create vX.Y.Z` - this creates and pushes the `vX.Y.Z` tag, which triggers `publish.yml`.
4. Confirm the `Publish` run succeeded (`gh run list`).
5. Confirm the version is **installable**, which is not the same question:

   ```bash
   curl -s https://pypi.org/simple/lyngdorf/ | grep X.Y.Z    # what installers read
   ```

   **Do not use the JSON API for this.** It was the documented check here
   and it is the wrong one. Measured on the 2.2.0 release: the wheel
   uploaded at 03:47:16Z, the JSON API showed both files immediately, and
   a `uv` resolve at 03:50:56Z still failed with "no version of
   lyngdorf==2.2.0". The two surfaces propagate independently and the
   simple index is the one that gates installs, so a green `Publish` run
   plus a JSON hit can still mean a consumer's CI cannot resolve the
   package. That cost a real CI cycle downstream.

   A `pip index versions lyngdorf` or a dry-run resolve answers the same
   question directly. Tell any consumer waiting on the release only after
   this passes, not after step 4.

**One-time setup** (already done for this repo): PyPI Trusted Publishing must be configured at https://pypi.org/manage/project/lyngdorf/settings/publishing/ with owner `fishloa`, repo `lyngdorf`, workflow filename `publish.yml`, no environment. Without it, `publish.yml` fails outright (no fallback token).
