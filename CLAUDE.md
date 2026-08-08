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

- `attrs` - Data classes (imported as `attr`)

## Testing Requirements

**IMPORTANT**: All features must have corresponding unit tests before being committed.

### Test Coverage Guidelines

1. **New Features**: Every new feature, method, or capability MUST have unit tests
   - Public API methods require tests
   - Feature detection methods (e.g., `has_zone_b_feature()`, `has_video_feature()`) require tests
   - Model-specific configurations require tests

2. **Test Patterns**: Follow existing patterns in `tests/basic_wiring_test.py`
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

See `tests/basic_wiring_test.py` for examples:
- `TestLyngdorfModel` class for model enum tests
- Feature detection tests (zone_b, video capabilities)
- Model lookup and configuration tests

## Release Process

Two separate workflows, two separate triggers:

- `.github/workflows/run-tests.yml` - runs on every push to `main` (tests, mypy, ruff, black).
- `.github/workflows/publish.yml` - runs on push of a `v*` **tag** only. Publishes to PyPI via OIDC Trusted Publishing (`pypa/gh-action-pypi-publish`, generates a PEP 740 attestation) - no static API token. Skips the build/publish steps if that version already exists on PyPI. Also verifies the tag matches `pyproject.toml`'s version and fails loudly if they disagree.

**A tag is the only thing that publishes.** Bumping `pyproject.toml` and pushing to `main` does *not* publish by itself - it only runs tests. This is deliberate: earlier the trigger was "push to `main` touching `pyproject.toml`", which meant a commit landing *after* the version-bump commit (but before a release was cut) silently never got published under that version. Tag-per-release closes that gap, since cutting the release is always the last step anyway.

To cut a release:

1. Bump `version` in `pyproject.toml`, commit, push to `main`.
2. Wait for `Run tests` to go green on that commit.
3. `gh release create vX.Y.Z` - this creates and pushes the `vX.Y.Z` tag, which triggers `publish.yml`.
4. Confirm the `Publish` run succeeded (`gh run list`) and the new version shows on PyPI (its JSON API can lag a few seconds after a real publish).

**One-time setup** (already done for this repo): PyPI Trusted Publishing must be configured at https://pypi.org/manage/project/lyngdorf/settings/publishing/ with owner `fishloa`, repo `lyngdorf`, workflow filename `publish.yml`, no environment. Without it, `publish.yml` fails outright (no fallback token).
