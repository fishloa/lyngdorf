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
