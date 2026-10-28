# Publication validation — 2026-10-27

- README reviewed; case-insensitive Aurora search returns no matches. Third-party asset attribution retained separately.
- Help and icon tests: 17 passed (8 upstream deprecation warnings), Linux offscreen Qt.
- `uv build`: wheel and source distribution built successfully. Wheel checked for reviewed README, icons and MIT license.
- Full suite: incomplete; process exited 139 during `test_app_integration.py::test_screening_tabs_real_sources`, with a segmentation fault in Qt worker/garbage collection. No application behavior change attempted for this publication.
- Original Windows ZIP passed CRC checks. Runtime/EXE preserved; offline README updated and license/notices added. No Windows runtime verification performed here.
- Source publishing excludes virtual environments, build output, crash dumps and local release ZIPs.
- Original supplied ZIPs retained outside this repository under the workspace backups directory.

## Windows screenshot follow-up — 2026-10-27

- Published portable EXE started successfully on a native Windows runner for main, AGF and Help captures; all three processes exited successfully.
- Main screenshot shows 452 materials; AGF shows one imported file and zero failed files; Help renders the cleaned offline manual. Images visually reviewed before publishing.
- Evidence and reproduction: [screenshot notes](docs/images/README.md), [successful Windows run](https://github.com/YonggangG/GlassWorkBench/actions/runs/40611155690).
- Initial GitHub cross-platform test runs [40610301469](https://github.com/YonggangG/GlassWorkBench/actions/runs/40610301469) and [40610320037](https://github.com/YonggangG/GlassWorkBench/actions/runs/40610320037) completed successfully. This does not erase the earlier local Linux segmentation fault.
- This follow-up changes repository documentation and adds a manual capture workflow only; existing release archives and application logic remain unchanged.
