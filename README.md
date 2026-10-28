# Glass Workbench

An offline desktop application to explore optical glass catalogs, calculate refractive index and dn/dT, screen material combinations, and manage Zemax AGF catalogs.

**No OpticStudio or Microsoft Excel installation is required.** The Windows portable package also runs without Python. Calculations and catalog processing run locally; the application does not need an internet connection during normal use.

> **Engineering scope:** Cooke and telescope results are first-order material/power screening candidates—not optimized lens prescriptions or verified image-quality predictions. Review source validity, extrapolation warnings, and model assumptions before engineering use.

## Contents

- [Install on Windows](#install-on-windows)
- [Quick start and in-app Help](#quick-start-and-in-app-help)
- [Run from source](#run-from-source)
- [Excel glass catalogs](#excel-glass-catalogs)
- [Six work areas](#six-work-areas)
- [Typical calculation workflows](#typical-calculation-workflows)
- [AGF catalog import, selection and export](#agf-catalog-import-selection-and-export)
- [Troubleshooting](#troubleshooting)
- [Tests](#tests)
- [Portable builds](#portable-builds)

## Install on Windows

### Recommended: download the portable application

1. Open this repository’s [Releases page](https://github.com/YonggangG/GlassWorkBench/releases) and select the desired release.
2. Download **`GlassWorkbench-v0.4.2-Windows-x64.zip`**, or the equivalent Windows ZIP for a newer release. GitHub's automatically generated **Source code (zip)** is not the ready-to-run application.
3. Extract **all** ZIP contents to a writable local folder. Do not run the EXE from inside the ZIP.
4. Download the two public manufacturer workbooks from the repository or release attachments if they are not already included:
   - `CDGM202609.xlsx`
   - `schott-optical-glass-overview-excel-format-en 202501113.xlsx`
5. Place the workbooks beside `GlassWorkbench.exe` for automatic discovery, or open them later with **Load Excel catalogs…**.
6. Double-click **`GlassWorkbench.exe`**.

The existing v0.4.2 Windows ZIP contains the application and its runtime dependencies, **but not the Excel workbooks**. After adding the catalogs, the application folder should look like this:

```text
GlassWorkbench/
├── GlassWorkbench.exe
├── _internal/
│   └── ... required runtime files ...
├── CDGM202609.xlsx
└── schott-optical-glass-overview-excel-format-en 202501113.xlsx
```

**Keep `_internal` alongside the EXE.** The executable is not a standalone single-file build. No installer, administrator installation, Python, uv, Excel, or OpticStudio is required for the portable app. Windows may apply your organization's download/security policy; use a trusted release and follow that policy rather than disabling protection.

To upgrade, save your exports, close the running application, and extract the new release into a separate folder. Copy the catalogs into the new application folder or select their existing locations. Do not overwrite a running executable.

### Platform support

| Platform | Recommended route | Verification status |
| --- | --- | --- |
| Windows x64 | Portable ZIP, or run from source | v0.4.2 packaged startup and Help smoke checks passed on Windows |
| Ubuntu | Run from source; optionally build locally | Setup scripts and CI configuration provided; native Ubuntu runtime validation has not been performed in this development environment |

## Quick start and in-app Help

Click **Help** at the top of the window, or press **F1**, to read this manual in a formatted, resizable viewer with section navigation. Help is included in the portable application and Python package and is available offline; opening an external reference link deliberately may require internet access.

1. Load the two official Excel catalogs using **Load Excel catalogs…**. Only their first worksheets are read. AGF catalog management also works without Excel files.
2. Choose global filters and a work area below. Inspect source/model details and warnings before using calculated results.
3. For **Cooke / Athermal 1550**, review the editable mounting/housing CTE as well as the wavelength, temperature, transmission and extrapolation settings.
4. For catalog export, open **AGF Catalogs**, add chosen materials to the export basket, review names and comments, then validate and save a new AGF plus its provenance report.

## Run from source

Use this route for development or when a suitable portable build is unavailable. The application uses Python/PySide6, Matplotlib, NumPy/SciPy, and openpyxl.

1. Download the repository using **Code → Download ZIP** and extract it, or clone `https://github.com/YonggangG/GlassWorkBench.git`.
2. Install Python **3.11–3.13** and [uv](https://docs.astral.sh/uv/getting-started/installation/), then reopen your terminal.
3. Open a terminal in the extracted project directory containing `pyproject.toml`.
4. Run:

```text
uv sync --group dev
uv run python -m glass_workbench
```

On Windows, `launch_windows.cmd` runs the application. On Ubuntu, use `bash launch_ubuntu.sh`. Both scripts change to the project root before launching, so catalog auto-discovery does not depend on the shell's starting directory. The first dependency installation needs internet access; normal catalog calculations run locally.

### Ubuntu system libraries

A Python virtual environment does not supply all Qt/OpenGL system libraries. On Ubuntu 22.04/24.04, install these before launching or running offscreen tests:

```bash
sudo apt-get update
sudo apt-get install -y \
  libegl1 libopengl0 libgl1 libdbus-1-3 libfontconfig1 \
  libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 \
  libxcb-randr0 libxcb-shape0 libxcb-xfixes0
```

Use a normal desktop session for interactive operation. `QT_QPA_PLATFORM=offscreen` is for automated tests, not for showing an application window. **Ubuntu execution and Ubuntu binary validation have not yet been performed in this Windows development environment.** The CI configuration provides a native Ubuntu verification path; its existence is not a claim that it has passed.

## Excel glass catalogs

The two public manufacturer workbooks below are the intended catalogs for this repository/release. Use the copies provided with the repository or as separate release attachments. If they are absent from a particular download, obtain the matching manufacturer catalogs separately. Place them in the project directory when running from source, beside the EXE for a portable build, or select their locations in the application:

| File | Imported worksheet | Expected records in the supplied edition |
| --- | --- | ---: |
| `CDGM202609.xlsx` | First worksheet, `optical glass` | 328 |
| `schott-optical-glass-overview-excel-format-en 202501113.xlsx` | First worksheet, `Preferred glasses` | 122 |

Only the first worksheet is imported. The CDGM `over!` sentinel is not a glass. Missing properties remain missing and can exclude a record from calculations requiring those properties; the expected total of 450 is not a guarantee of 450 eligible glasses for every calculation.

`Glasses_1550nm.xlsx`, `Corning_FusedSilica.csv`, and `Athermal_Triplet_1550nm_Summary_2.pptx` are **not application catalogs**. The presentation informs the Cooke screening equations, but its derived workbook has inconsistent CTE conventions and undocumented cross-vendor price scaling. Corning HPFS 7980 is now supplied as a separate source-based supplemental material, not copied from that legacy workbook. The application preserves the input workbooks. They may be distributed alongside the app; the current PyInstaller build specification does not embed or copy them automatically. Manufacturer data and attribution remain distinct from application source code.

## Supplemental materials: HPFS 7980 and silicon

Two bundled source-based records are available without additional Excel files: **Corning:HPFS 7980** and **Infrared:Silicon**. Their individual checkboxes start enabled. With both official workbooks loaded, the full list contains **452 materials**; the popular preset contains **146** when both supplements are selected. Disabling the checkboxes restores the original 450/144 populations. Supplements bypass H-/N-/MA workbook presets, but explicit supplier and name-prefix filters still apply.

The supplemental checkboxes are independent: deselecting silicon does not deselect Corning. A checked material is **available for consideration**, not required in every combination or guaranteed to appear among the retained best results. The Cooke completion summary distinguishes eligible glasses, accepted combinations, and best results retained. Increase **Results retained** to inspect lower-ranked combinations.

For the supplied catalog editions, using MA, 1550 nm, 20 °C, Al6061 23.6 ppm/K, maximum normalized power 8, Cooke `+ − +`, minimum transmission 0.97, and both extrapolation/unknown-transmission permissions: with silicon deselected, Corning remains in the 65-glass eligible pool and appears in 66 accepted combinations. Its best combination ranks 346 (RMS normalized power approximately 3.80163), so the top 50 contain none; retaining 500 shows four Corning combinations. With silicon enabled, the best result pairs H-ZF62, HPFS 7980 and silicon (RMS approximately 2.05322). These are first-order rankings for these settings, not validated lens prescriptions or a reason to force a material into the results. MA excludes SCHOTT workbook entries, which lack that melt category.

Silicon is a crystalline infrared material, not a visible optical glass: it has no invented nd/Vd/PgF values, appears in the table rather than the visible maps, and is always excluded from C/d/F telescope screening—even if extrapolation is enabled.

For a 1550-nm triplet search including the supplements:
1. Leave the desired supplemental-material checkboxes enabled.
2. Enable **Allow flagged thermal / dispersion extrapolation** when using HPFS 7980 at 1550 nm, outside the cited brochure's dispersion-fit interval.
3. Enable **Allow unknown internal transmission** if you want materials lacking verified 10-mm internal-transmission data to participate. This permission is separate from extrapolation and is off by default.
4. Search and inspect each candidate's warnings and provenance. Unknown transmission remains blank/unknown; the known-only minimum is reported separately, and known values below the threshold still reject. No transmission or price has been fabricated.

The supplied [Corning 2015 brochure](https://www.corning.com/media/worldwide/csm/documents/HPFS_Product_Brochure_All_Grades_2015_07_21.pdf) was partially readable through web extraction, but direct full retrieval was blocked. The implementation cross-checks the complete 2014 Corning brochure hosted by Edmund Optics; it does not claim full verification of the 2015 edition. Source-native nitrogen/reference-medium and near-room-temperature assumptions are explicitly documented in the bundled model notes. Silicon uses the temperature-dependent absolute-index model of [Frey, Leviton and Madison (2006)](https://arxiv.org/abs/physics/0606168); its measured 20–300 K range includes 20 °C but not 50 °C. Inspect extrapolation warnings before engineering use. The published silicon coefficient model's analytic dn/dT also differs from one tabulated thermo-optic checkpoint (177.462 versus 187 ppm/K at 1.5 µm and 295 K). The app retains the published coefficients, reports this discrepancy, and does not claim that the derivative is independently validated to that table.

## Six work areas

- **Glass Maps:** catalog exploration using nd–Vd and Pg,F–Vd maps.
- **Glass Thermal / Glass dn/dT:** wavelength- and temperature-dependent glass refractive indices and thermal derivatives. Distinguish index relative to air from absolute index. The bottom curve plot is hidden by default to give the glass table more space; enable **Show curve plot** to display it.
- **Air:** Ciddor phase refractive index as a function of wavelength, temperature, pressure, humidity, and CO2.
- **Cooke / 1550 nm:** first-order three-glass power screening with thermal and Petzval constraints. A Cooke `+ − +` candidate is not the same as an unrestricted presentation-style triplet.
- **Visible Telescope:** C/d/F screening of a thin cemented triplet followed by an air-spaced corrective singlet, independently normalized at the d line.
- **AGF Catalogs:** inspect Zemax text catalogs and combine selected imported AGF or loaded Excel materials into a new catalog. Global filters apply only to its Excel-derived entries, **not loaded AGF files**. Local filters apply to both sources; AGF imports do not change the calculation tabs.

The global **H-/N- name grouping and MA melt-frequency category are separate filters**. CDGM H- and SCHOTT N- refer to glass-name prefixes; CDGM `MA` is an exact melt-frequency category, not a name prefix and not the category `A`. Where using the popular combined selection, the intended expression is `(CDGM H- AND MA) OR SCHOTT N-`, not an AND across both manufacturers.

## Typical calculation workflows

### Explore the catalogs

1. Load one or both Excel workbooks.
2. Use the global supplier, name-group, melt-category, and name-prefix filters to narrow the material pool.
3. Open **Glass Maps** to compare visible optical properties and inspect the corresponding table.
4. Use **Source / model details** to review the numerical conventions and supplemental-material references.

Silicon has no assigned visible nd/Vd values and therefore does not appear as a point on the visible glass maps. It remains available in appropriate infrared calculations.

### Calculate glass refractive index and dn/dT

1. Open **Glass dn/dT** and select the desired wavelength and temperature.
2. Run the calculation for the current filtered pool and inspect the results and warnings.
3. Distinguish **absolute** refractive index/derivative from values **relative to air**.
4. Select a material and enable **Show curve plot** to display its curve. The plot is hidden initially to leave more space for the table.

### Calculate the refractive index of air

Open **Air**, set the wavelength and atmospheric conditions, and run the calculation. Review pressure, humidity, CO2, and temperature-derivative hold conditions. The model evaluates phase refractive index, not group index.

### Search Cooke / Athermal 1550 material combinations

1. Choose the glass pool using the global filters. Leave Corning and/or silicon checked if you want them considered.
2. Open **Cooke / Athermal 1550**. Review wavelength, temperature, target EFL, maximum normalized power, power-sign pattern, and **Results retained**.
3. Set **Mounting / housing CTE** for your mount. The default **23.6 ppm/K** is an Al6061 aluminum modeling assumption; it is editable.
4. Review the minimum internal transmission and the separate permissions for extrapolation and unknown transmission. Enable either permission only when its limitations are acceptable.
5. Click **Search glass combinations**. Select a result to inspect its powers, warnings, and run metadata.

The search ranks accepted candidates by RMS normalized power; a smaller value ranks ahead. A selected material can remain eligible without appearing in the retained top results. Increase **Results retained** if necessary. These results do not constitute a spaced Cooke prescription or an MTF evaluation.

### Screen a visible telescope material combination

Open **Visible Telescope**, select a visible-material pool, and set the EFL, normalized air gap, power limit, and search/refinement budgets. Run the search and inspect C/d/F focal spread, Petzval, and coverage information. The model is a thin cemented triplet plus an air-spaced thin singlet. Silicon is excluded. Increasing the search budget does not establish a globally optimal physical lens.

## AGF catalog import, selection and export

The **AGF Catalogs** tab is a separate catalog-management workspace:

1. Use **Load AGF files…** to open one or several `.agf` files. **Loaded AGF entries ignore all global filters.** Global supplier, name preset, melt category and name-prefix filters apply only to Excel-derived entries in this browser. The tab's local source/search/formula filters apply to both sources.
2. Select material rows and add them to the **export basket**. Inspect the interpreted properties, source line numbers, diagnostics and original AGF text. The basket retains source snapshots across sorting, filtering and workbook reloads.
3. Combine any number of imported AGF and convertible Excel entries. Names outside the conservative export-name policy are automatically repaired when added: for example, `H-K9L*` becomes **`H-K9L_ST`**. A changed **export name is shown in red**, with the original name retained beside it. You may still rename explicitly. Duplicate already-valid names require renaming or removing a basket item; different source identities are never silently merged.
4. Use **Export catalog comment…** to view source catalog comments and edit the new combined catalog's comment. The four basket actions—**Rename…**, **Comment…**, **Remove**, and **Clear**—share one row. Select one basket glass and use **Comment…** to view its original comment and edit the output comment. Save commits an edit; Cancel leaves it unchanged; **Reset to original** restores source-preserving behavior when saved. Saving an empty output comment clears that comment. These changes affect only the new export, not your loaded files or optical coefficients.
5. Validate and preview the output. Acknowledge conversion warnings deliberately, then save a **new `.agf`** and its neighboring **`.metadata.json`** provenance report. Name/comment edits invalidate the previous preview: validate again before exporting. Warning acknowledgment does not override blocking structural errors or unresolved duplicate names.

### Filter scope in the AGF tab

| Material source | Global filters | Local source/search/formula filters |
| --- | --- | --- |
| Loaded Excel workbooks | Apply, using original workbook metadata | Apply |
| Loaded `.agf` files | **Do not apply** | Apply |
| Existing export basket | No entries removed | No entries removed |

Changing a global filter clears only newly excluded **Excel-derived** browser selections. Imported AGF selections remain available, even if they do not match the global supplier, Popular/MA preset or name prefix. Eligible selections hidden only by local filters remain selected. Already-added basket entries remain intact.

Imported source supplier labels and exact-name workbook melt-category matches are **informational only**. A filename-based CDGM/SCHOTT supplier assignment can be corrected with the source selector, but it does not make imported AGF materials subject to global filters. Native AGF melt-frequency integers 1–5 are never translated into MA/A/etc. These annotations never change optical coefficients or exported raw records. Bundled supplemental models remain excluded from direct conversion; supplemental checkboxes do not hide imported AGF equivalents.

AGF input retains comments, unknown records, extra fields and original coefficient text. UTF-16 and UTF-8 input are supported; any legacy decoding fallback is reported. Combined output uses UTF-16 LE with BOM and CRLF. Mixed-encoding exports preserve record text except authorized output-name and glass-comment overrides, not byte-identical source files. Original Excel/AGF catalogs are not overwritten, and the app does not install catalogs into OpticStudio.

Catalog comments use `CC` records; individual glass comments use `GC` records. Newly added basket glasses default to **only the first line** of their effective glass comment, for example `Generated from CDGM; source CDGM202609.xlsx, sheet optical glass, row 18`. Original full comments remain available in the read-only source view and provenance. You may edit the effective comment or use **Reset to original** to restore all original GC records. Existing basket edits are not shortened again by filtering, sorting or re-adding an already-present glass. The backend preservation API still retains all original comments unless an override is supplied. Edited text is serialized as comments, never interpreted as optical records. Source catalog headers and original/effective output comments remain available in the provenance report. Clearing or rewriting a comment does **not** remove parser/conversion diagnostics or make an incomplete material fully characterized.

**Interpretation is not automatic numerical-model support.** Formula identifiers and properties can be inspected even when the application does not evaluate that formula. Imported AGFs do not enter the existing maps, thermal calculations or screening engines. Structurally impaired records are blocked by default; explicitly preserving unresolved imported records is an archival operation, not a claim that OpticStudio will accept them. Generated invalid records and unresolved duplicate names remain blocking.

Excel conversion supports the existing six-coefficient polynomial and three-term Sellmeier models. It reorders Sellmeier coefficients for AGF, converts CTE units, retains complete standard thermal data, and exports original 10-mm internal-transmission samples. Missing values are not replaced with physical zeroes; omitted properties and source-model assumptions appear in the export diagnostics and manifest. The `LD` limits derived from source spectral checkpoints are conservative working limits, **not manufacturer-certified dispersion validity**. SCHOTT's second CTE covers 20–300 °C rather than the AGF convention's usual 100–300 °C; this difference is retained in warnings and provenance (OpticStudio documents that second field as currently unused). Supplier-native prices remain incomparable across suppliers. `PgF` is not the AGF `dPgF` anomaly.

The bundled Corning 7980 and silicon models are **not directly converted** to standard AGF coefficients because their reference-medium/temperature models differ. An existing record for either material imported from an AGF can still be selected and preserved. No automatic fitting is performed.

You can also open catalogs explicitly from the command line:

```text
uv run python -m glass_workbench --agf "BERMAN.AGF" --agf "SCHOTT.AGF"
```

The GUI export basket uses a conservative app naming policy: 1–32 ASCII letters/digits or `_ . + ( ) -`; this is an app restriction, not a claim about every OpticStudio version. When a new Excel or imported AGF entry is added, `*` becomes `_ST`, other unsupported characters become `_`, and overlong names are shortened. Automatically repaired names receive suffixes such as `_2` when needed to avoid case-insensitive collisions with existing or incoming valid names. Existing manual overrides are not regenerated by filtering or sorting. Red names mean the output name differs from the original—not that the glass coefficients were changed. Name repair does not fix malformed source records: whitespace or control characters that already disrupted a generated/imported `NM` record still produce blocking diagnostics. The backend preservation API can still retain structurally valid unchanged imported names; GUI additions deliberately apply the consistent conservative policy. Non-ASCII comments remain supported.

Export is deliberately blocked into directories named `Glasscat` / `Glass Catalogs`; save to a separate working folder and install manually after inspection. Keep the provenance report alongside the AGF: missing `TD` or other omitted properties can lead to OpticStudio defaults, so an incomplete export must not be treated as a fully characterized thermal material.

Format reference: [Ansys OpticStudio AGF/BGF specification](https://ansyshelp.ansys.com/public/Views/Secured/Zemax/v251/en/OpticStudio_User_Guide/OpticStudio_Help/topics/The_AGF_BGF_File_Formats.html). Export validation is a structural/numerical check within this application, not native OpticStudio acceptance testing.

### Cooke assumptions and defaults

The screening equations use normalized element powers `y_i`:

```text
sum(y_i) = 1
sum(y_i * psi_i) = -alpha_housing
sum(y_i / n_i) = 0
psi_i = (dn_relative/dT)_i / (n_i - 1) - alpha_glass_i
```

Defaults are 1550 nm, 20 °C, Al6061 housing expansion 23.6 ppm/K, EFL 90 mm, maximum absolute normalized power 8, and a 10-mm internal-transmission threshold of 0.97. An interpolated transmission is an estimate between source samples, not a measured 1550-nm value. The presentation's f/2.7 is context, not a performance prediction of this model.

**Mounting / housing CTE is editable.** The default **23.6 ppm/K** represents the application's **Al6061 aluminum assumption**, not a requirement to use aluminum. For another mount, enter its linear CTE in the same control (`1 ppm/K = 10⁻⁶/K`), using an appropriate value for the actual alloy/material and operating temperature interval. The selected numeric value is passed into the screening equations and retained in result metadata. This is a constant, first-order housing-expansion approximation—not a temperature-dependent structural model, a full mount/lens thermal analysis, or a universal CTE for every aluminum alloy.

### Telescope assumptions and defaults

The visible calculation uses C/d/F wavelengths near 656.2725/587.5618/486.1327 nm on the conventional air scale (converted internally to vacuum). By default the cemented group must have positive d-line power, appropriate to a telescope objective; the checkbox may be disabled for unrestricted group exploration. Its editable example defaults are **EFL 500 mm** and **gap/EFL ratio 0.1** (50 mm at the default EFL); these are not a user-specified telescope prescription. The cemented group and separate singlet are thin, paraxial models. Chromatic focus is assessed at a common image plane through the separated system, not by treating the elements as an unspaced sum. The Cooke housing athermalization target does not apply to this tab.

A reported candidate is **best found within the bounded heuristic search**, not a global optimum. Even exhaustive enumeration of a small glass pool does not prove a globally optimal continuous prescription. Results are glass/power suggestions for later optical design, not an optimized or manufacturable lens. They do not establish spherical-aberration, astigmatism, spherochromatism, MTF, or tolerance performance.

## Thermal and catalog cautions

- CTE is catalog-specific: CDGM source values use **10^-7/K**, whereas the SCHOTT CTE convention uses **10^-6/K**. Do not transfer raw numbers between suppliers or reuse the legacy workbook's mixed scales. Calculations require consistent SI expansion units.
- Dispersion and thermal coefficients must be interpreted with each manufacturer's formula, reference temperature, wavelength convention, and validity limits. Transmission coverage alone does not establish a dispersion or thermal validity range.
- CDGM polynomial records lack supplied NIR spectral checkpoints. Their 1550-nm extrapolations must not be treated as manufacturer-validated or silently included in default NIR ranking.
- An instantaneous `dn/dT` is not the same quantity as a manufacturer's interval-averaged thermal table entry. The temperature interval and reference atmosphere matter when comparing values.
- Absolute glass index, reference-air relative index, and index relative to the chosen atmosphere are distinct. The temperature derivative of a relative index includes the air derivative; do not subtract a constant air correction.
- Air defaults are dry air at 101325 Pa and 450 ppm CO2. Specify derivative hold conditions: fixed pressure/CO2 with fixed RH differs from fixed water mole fraction. Ciddor here means **phase**, not group, refractive index.
- Missing coefficients or unsupported input domains are not evidence of zero thermo-optic response. Review exclusions, assumptions, and any extrapolation warning before comparing candidates.
- Supplier-native relative prices are **not comparable across suppliers**. They are neither currency prices nor a valid combined cost without an explicitly justified user conversion.

### Reference conventions and validity

[SCHOTT TIE-19](https://media.schott.com/api/public/content/0dcd87a2d36942a3946d033f0a9065e6?v=940fa3fb&download=true) specifies a 20 °C reference temperature and vacuum wavelength for the thermal model, with a stated range of 0.365–1.014 µm and −100 to +140 °C. **SCHOTT thermal calculations at 1550 nm are outside that documented range and require explicit extrapolation opt-in.** A default 1550-nm control value is not a manufacturer-validity claim. The model evaluates an absolute-index increment and converts back to relative index using the air-index quotient.

[SCHOTT TIE-29](https://media.schott.com/api/public/content/8afd09ccdf4243e890df9f875b1b5579?v=ff3f35d1&download=true) describes air wavelengths for the spectral indices used by the dispersion model. Conversion from the public vacuum-wavelength input uses dry Ciddor air at 20 °C, 101325 Pa, and 450 ppm CO2. This is an approximation: the manufacturer's exact humidity/CO2 reference conditions are not established here. The implementation restricts dispersion use to supplied spectral-index coverage rather than inferring validity from transmission samples.

The **CDGM thermal convention remains a table-tested assumption, not independently verified manufacturer documentation**; large inconsistencies are rejected by default. SCHOTT's 10^-6/K CTE scale is the adopted standard convention, but the official TIE-31 PDF's unit statement has not been independently reverified in this implementation. Check these assumptions before engineering use. The air implementation's supported range is 0.3–1.7 µm, −40 to +100 °C, and 10–140 kPa, with physical humidity checks; choosing fixed RH versus fixed water fraction changes its temperature derivative.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| EXE fails to start or reports missing DLLs | Extract the complete Windows ZIP. Keep the EXE and its `_internal` directory together; do not copy only the EXE. |
| No Excel glasses appear | Use **Load Excel catalogs…** to select the two supported workbooks. For automatic discovery, place them beside the portable EXE or in the source project root. |
| A glass disappears after filtering | Review supplier, name preset, melt category, name-prefix, and supplemental selections. A missing melt category is not the same as MA. |
| Corning disappears from Cooke results after disabling silicon | It may be outside the retained top results, not excluded. With the documented MA example, its best silicon-free rank is 346; try retaining 500. |
| A search returns few or no combinations | Review the filtered pool, missing coefficients, power/sign constraints, and transmission/extrapolation diagnostics. Do not assume unknown properties are zero or perfect transmission. |
| **Export new AGF** remains disabled | Validate the current basket and inspect blocking errors. Resolve duplicate names or invalid records, acknowledge acceptable warnings, and validate again after name/comment edits. |
| The Glass dn/dT plot is missing | Enable **Show curve plot** and select a material row. |
| `uv` is not recognized | Install uv, reopen the terminal, and run from the directory containing `pyproject.toml`. |
| Ubuntu reports a Qt/xcb/OpenGL error | Install the listed system libraries and use a graphical desktop session. Offscreen mode is for tests only. |
| Windows shows the old application icon | Close and reopen the app; Windows may also require recreating an old shortcut because of icon caching. |

Press **F1** or click **Help** for the offline manual. When reporting a problem through the repository's Issues page, if enabled, include the app version, operating system, catalog edition, relevant filters/settings, and the full error or diagnostic message. Do not attach confidential catalogs or exports.

## Tests

```bat
rem Windows Command Prompt
set QT_QPA_PLATFORM=offscreen
uv run python -m pytest -q -ra
```

```bash
# Ubuntu
QT_QPA_PLATFORM=offscreen uv run python -m pytest -q -ra
```

Synthetic data exercises the import/numerical/UI paths without external catalogs. Tests requiring the actual manufacturer workbooks skip when those files are absent; skipped integration tests are not a validation of the source catalogs. Include the two public workbooks for their catalog-dependent checks; keep any unrelated confidential data out of CI. `.github/workflows/test.yml` defines Windows and Ubuntu tests with offscreen Qt and supports opt-in native portable builds through manual workflow dispatch. Its presence does not establish that a published CI run has passed.

## Portable builds

Build on the **target operating system** with its native Python environment; PyInstaller does not cross-compile Windows binaries into Linux binaries.

```bat
rem On Windows
build_windows.cmd
```

```bash
# On Ubuntu itself
bash build_ubuntu.sh
```

Both scripts run `uv sync --group dev` and build `packaging/GlassWorkbench.spec`. They refresh the `build/` working directory and replace the matching generated `dist/GlassWorkbench/` output. Windows uses a windowed **onedir** build, preferred over onefile extraction:

- Windows executable: `dist/GlassWorkbench/GlassWorkbench.exe`
- Linux executable: `dist/GlassWorkbench/GlassWorkbench`

Distribute the **entire GlassWorkbench directory**, including `_internal`, not just the executable. The frozen entry wrapper uses an absolute package import and changes the working directory to the executable's directory. Place authorized external catalogs beside the executable for discovery, or use explicit file selection. No Excel catalogs, presentation, or legacy data files are included by the spec. A recipient of a portable build does not need Python or uv, but Linux still needs compatible system libraries. Build Linux releases on the oldest Ubuntu version you intend to support and test on each supported target.

The workflow uploads only the generated application directory, never external source catalogs. Offscreen source tests are not a packaged interactive smoke test: validate startup, catalog selection, calculations, and exports on each release target before distribution.

For bounded startup checks, `--smoke-test` waits for catalog imports and exits. Add `--smoke-help` to open the actual bundled Help viewer before exiting; it requires `--smoke-test`. With `--screenshot`, this captures Help instead of the main window:

```text
GlassWorkbench.exe --no-autoload --smoke-test --smoke-help --screenshot help.png
```

Help is bundled both in portable builds and in the Python wheel. Reading it does not depend on a README in the launch directory or on an internet connection.

## Repository layout

- `src/glass_workbench/`: application code and bundled assets.
- `tests/`: numerical, catalog and offscreen GUI tests.
- `packaging/` and build scripts: native portable builds.
- `reference/`: supporting optical-material data and presentation.
- Manufacturer Excel catalogs are provided at the repository root.
- Portable downloads are hosted in [GitHub Releases](https://github.com/YonggangG/GlassWorkBench/releases); local `release/` files are excluded from Git.

## License

Application source code is available under the [MIT License](LICENSE). Third-party assets, manufacturer data, reference publications and dependencies retain their own terms; see [third-party notices](THIRD_PARTY_NOTICES.md).

## Publication validation

The 2026-10-27 Linux publication check encountered a segmentation fault in the full offscreen test suite during `test_app_integration.py::test_screening_tabs_real_sources` (Qt worker/garbage collection). Full-suite validation remains incomplete. The supplied Windows executable was not rebuilt or runtime-tested during publication. See [VALIDATION.md](VALIDATION.md) for the bounded checks.
