# Windows application screenshots

The PNG files in this directory are actual widget captures from the published
GlassWorkbench v0.4.2 Windows x64 portable executable on `windows-latest`.
No AI-generated imagery or simulated application UI is used.

- `windows-main.png`: main Glass Maps window with both manufacturer workbooks.
- `windows-agf.png`: AGF Catalogs with the supplied `reference/MISC.AGF` loaded.
- `windows-help.png`: bundled offline Help.

Capture run: https://github.com/YonggangG/GlassWorkBench/actions/runs/40611155690

To reproduce, manually dispatch `.github/workflows/screenshots.yml`. It downloads
the published Windows ZIP, adds the repository's two manufacturer workbooks and
sample AGF next to the EXE, and invokes the existing `--smoke-test --screenshot`
options. AGF uses `--agf MISC.AGF`; Help uses `--smoke-help`. The workflow checks
exit codes and output file sizes and uploads the PNGs as an artifact. Review the
images before replacing committed screenshots.

Qt captures the application widget, not the Windows desktop/title-bar frame.
These startup captures verify the shown windows, not every calculation or export
workflow. The bundled Help reflects the release manual, not subsequent README
edits on main. Existing release downloads are not modified by this documentation
update.
