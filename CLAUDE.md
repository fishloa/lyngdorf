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
