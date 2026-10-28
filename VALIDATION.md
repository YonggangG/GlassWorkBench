# Publication validation — 2026-10-27

- README reviewed; case-insensitive Aurora search returns no matches. Third-party asset attribution retained separately.
- Help and icon tests: 17 passed (8 upstream deprecation warnings), Linux offscreen Qt.
- `uv build`: wheel and source distribution built successfully. Wheel checked for reviewed README, icons and MIT license.
- Full suite: incomplete; process exited 139 during `test_app_integration.py::test_screening_tabs_real_sources`, with a segmentation fault in Qt worker/garbage collection. No application behavior change attempted for this publication.
- Original Windows ZIP passed CRC checks. Runtime/EXE preserved; offline README updated and license/notices added. No Windows runtime verification performed here.
- Source publishing excludes virtual environments, build output, crash dumps and local release ZIPs.
- Original supplied ZIPs retained outside this repository under the workspace backups directory.
