Before adding code, prefer the cheapest durable solution: clarify or narrow the workflow, reuse existing Python libraries or framework features, or simplify the UI/backend/module boundary.

When new code is justified, keep it minimal, local to the responsible layer, consistent with the project’s existing libraries and patterns, and Pythonic where that does not conflict with those conventions.

Use `.\rg.exe` instead of bare `rg`.

For PowerShell commands that run `uv`, `pytest`, or `ruff`, initialize workspace-local cache/temp dirs once per shell session:

```powershell
$env:UV_CACHE_DIR = "$PWD\.uv-cache"
$env:TEMP = "$PWD\.tmp"
$env:TMP = "$PWD\.tmp"
$env:RUFF_CACHE_DIR = "$PWD\.ruff_cache"
```

Run pytest with:
```powershell
uv run pytest --basetemp="$PWD\.pytest-tmp" -p no:cacheprovider ...
```
