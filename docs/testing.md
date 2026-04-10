# Testing

This project uses `pytest` for unit testing.

## Run tests

Install developer dependencies first:

```powershell
pip install -r requirements-dev.txt
```

Then run:

```powershell
pytest -q
```

## Current test coverage

The current suite includes:
- `tests/test_config.py` — configuration validation and loading behavior.
- `tests/test_openwebui.py` — OpenWebUI health checks, startup fallback behavior, and serial port availability handling.

## Recommended workflow

1. Install or update dependencies.
2. Run `pytest -q`.
3. Review failures and repeat until all tests pass.

## Notes

The `requirements-dev.txt` file contains test and development dependencies used by CI.
