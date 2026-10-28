"""Compact layout defaults and output-only first-line basket comments."""
import json
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import Qt

from glass_workbench.catalogs.agf import load_agf, parse_agf
from glass_workbench.catalogs.agf_export import material_comment
from glass_workbench.contracts import Catalog, Environment, Glass
from glass_workbench.ui.agf import AgfTab, CommentDialog
from glass_workbench.ui.main_window import MainWindow


def imported_block(comment_records):
    return ("NM IMPORTED 1 0 1.5 60 0 0\r\n" + comment_records
            + "CC Keep material CC\r\n! Keep annotation\r\n"
            "CD 2.250000000000000000 0 0 0 0 0\r\nLD 0.4 0.7\r\n")


@pytest.mark.parametrize("size", [(1480, 980), (1060, 720)])
def test_basket_four_actions_share_one_row_with_count_above(qtbot, size):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    tab = window.agf
    window.tabs.setCurrentWidget(tab)
    window.resize(*size)
    window.show()
    qtbot.wait(50)
    assert (window.width(), window.height()) == size
    buttons = [tab.rename_button, tab.glass_comment_button, tab.remove_button, tab.clear_button]
    # At minimum size the existing content is horizontally scrollable; reveal
    # the rightmost action before checking that the entire compact row fits.
    tab.scroll_area.ensureWidgetVisible(tab.clear_button)
    qtbot.wait(10)
    viewport = tab.scroll_area.viewport()
    rects = [button.rect().translated(button.mapTo(viewport, button.rect().topLeft())) for button in buttons]
    assert len({rect.top() for rect in rects}) == 1
    assert len({rect.bottom() for rect in rects}) == 1
    for button, rect in zip(buttons, rects):
        assert button.isVisible()
        assert viewport.rect().contains(rect), button.text()
        assert button.width() >= button.minimumSizeHint().width(), button.text()
    assert all(left.right() < right.left() for left, right in zip(rects, rects[1:]))
    label = tab.basket_label
    label_rect = label.rect().translated(label.mapTo(viewport, label.rect().topLeft()))
    assert label_rect.bottom() < rects[0].top()
    assert label.text() == "Export basket: 0"
    assert tab.source_view.height() >= 140 and tab.basket_view.height() >= 140
    if size == (1480, 980):
        assert tab.scroll_area.verticalScrollBar().maximum() == 0


@pytest.mark.parametrize("size", [(1480, 980), (1060, 720)])
def test_thermal_entire_curve_pane_hidden_and_toggle_replots_selection(qtbot, monkeypatch, size):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    tab = window.thermal
    window.tabs.setCurrentWidget(tab)
    window.resize(*size)
    window.show()
    qtbot.wait(50)
    assert not tab.show_plot.isChecked()
    assert tab.plot_container.isHidden()
    assert not tab.curve.isVisible() and not tab.plot.isVisible()
    hidden_height = tab.table.height()
    calls = []
    monkeypatch.setattr(tab, "plot_selected", lambda: calls.append("plot"))
    qtbot.mouseClick(tab.show_plot, Qt.MouseButton.LeftButton)
    qtbot.wait(30)
    assert tab.plot_container.isVisible() and tab.curve.isVisible() and tab.plot.isVisible()
    assert calls == ["plot"]
    assert tab.table.height() < hidden_height
    qtbot.mouseClick(tab.show_plot, Qt.MouseButton.LeftButton)
    qtbot.wait(30)
    assert tab.plot_container.isHidden()
    assert not tab.curve.isVisible() and not tab.plot.isVisible()
    assert tab.table.height() >= hidden_height - 2
    assert calls == ["plot"], "Hiding must not compute a new curve"


def test_show_curve_uses_selected_sorted_glass_and_calculation_context(qtbot, monkeypatch):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    tab = window.thermal
    window.tabs.setCurrentWidget(tab)
    window.show()
    first = Glass("A", "SAME", "", 1.5, 60)
    selected = Glass("Z", "SAME", "", 1.6, 50)
    environment = Environment()
    tab.last_context = ([first, selected], 0.905, 50, environment, True)
    calls = []

    def evaluate(glass, wavelength, temperature, env, extrapolate):
        calls.append((glass, wavelength, temperature, env, extrapolate))
        return SimpleNamespace(dn_relative=(wavelength + temperature) * 1e-6,
                               dn_absolute=(2 * wavelength + temperature) * 1e-6)

    monkeypatch.setattr("glass_workbench.optics.thermal.evaluate", evaluate)
    tab.table.set_rows([{"supplier": g.supplier, "glass": g.name} for g in (first, selected)])
    tab.table.view.sortByColumn(tab.table.model.columns.index("supplier"), Qt.SortOrder.DescendingOrder)
    row = next(i for i, item in enumerate(tab.table.model.rows) if item["supplier"] == "Z")
    tab.table.view.selectRow(row)
    # Changing live controls must not silently replace the last calculated context.
    tab.wavelength.setValue(1550)
    tab.temperature.setValue(20)
    calls.clear()
    tab.show_plot.setChecked(True)
    assert len(calls) == 61
    assert all(g is selected and env is environment and ext for g, _, _, env, ext in calls)
    axes = tab.plot.axes[0]
    xs = np.linspace(25, 75, 61)
    np.testing.assert_allclose(axes.lines[0].get_xdata(), xs)
    np.testing.assert_allclose(axes.lines[0].get_ydata(), xs + .905)
    np.testing.assert_allclose(axes.lines[1].get_ydata(), xs + 1.810)
    assert selected.uid in axes.get_title()
    assert axes.get_xlabel() == "Temperature (°C)"
    calls.clear()
    tab.curve.setCurrentIndex(1)
    assert len(calls) == 61
    xs = np.linspace(655, 1155, 61)
    np.testing.assert_allclose(axes.lines[0].get_xdata(), xs)
    np.testing.assert_allclose(axes.lines[0].get_ydata(), 50 + xs / 1000)
    assert axes.get_xlabel() == "Vacuum wavelength (nm)"
    assert all(g is selected and t == 50 for g, _, t, _, _ in calls)


@pytest.mark.parametrize("records, expected", [
    ("", None), ("GC\r\n", None), ("GC One line\r\n", None),
    ("GC First\r\nGC Second\r\n", "First"),
    ("GC\r\nGC Second\r\n", ""),
    ("GC First\r\nGC\r\n", "First"),
])
def test_only_new_multiline_comments_get_first_physical_line(qtbot, records, expected):
    tab = AgfTab()
    qtbot.addWidget(tab)
    document = parse_agf(imported_block(records), source_path="comments.agf")
    tab.imported((tab.generation, [document], []))
    material = document.materials[0]
    tab.selected_ids = {material.identity}
    tab.add_selected()
    assert tab.basket[material.identity].glass_comment == expected
    assert tab.basket[material.identity].material is material
    assert material.raw_text == imported_block(records)


@pytest.mark.parametrize("kind", ["imported", "generated"])
def test_new_comment_preview_manifest_manual_edit_and_reset_are_output_only(qtbot, monkeypatch, tmp_path, kind):
    tab = AgfTab()
    qtbot.addWidget(tab)
    source_bytes = None
    if kind == "imported":
        source = tmp_path / "original.agf"
        source_bytes = ("CC Source header\r\n" + imported_block(
            "GC First physical line\r\nGC Second source line\r\nGC Third source line\r\n")).encode("utf-8")
        source.write_bytes(source_bytes)
        document = load_agf(source)
        tab.imported((tab.generation, [document], []))
    else:
        glass = Glass("CDGM", "GENERATED", "500600", 1.5, 60, dispersion_model="polynomial",
                      dispersion=(2.25, 0, 0, 0, 0, 0), source_file="workbook.xlsx", source_sheet="First",
                      source_row=2, source_hash="v1", wavelength_range=(0.4, 0.7),
                      remarks="Workbook first remark\nWorkbook second remark")
        tab.update_workbooks([Catalog("CDGM", "workbook.xlsx", "First", "v1", [glass])])
    material = next(iter(tab.materials.values()))
    raw = material.raw_text
    original = material_comment(material)
    assert len(original.splitlines()) > 1
    first_line = original.splitlines()[0]
    tab.selected_ids = {material.identity}
    tab.add_selected()
    assert tab.basket[material.identity].glass_comment == first_line

    def check_preview(expected, override):
        tab.acknowledge.setChecked(True)
        preview = tab.validate_export()
        assert preview.valid, preview.errors
        entry = preview.manifest["materials"][0]
        assert entry["original_glass_comment"] == original
        assert entry["effective_glass_comment"] == expected
        assert entry["glass_comment_override"] == override
        exported = parse_agf(preview.text).materials[0]
        assert material_comment(exported) == expected
        assert [(r.mnemonic, r.tokens) for r in exported.records if r.mnemonic != "GC"] == [
            (r.mnemonic, r.tokens) for r in material.records if r.mnemonic != "GC"]
        assert material.raw_text == raw and material_comment(material) == original
        row = next(i for i, record in enumerate(tab.basket_model.rows)
                   if record["identity"] == material.identity)
        tab.basket_view.selectRow(row)
        assert tab.raw.toPlainText() == raw.replace("\r\n", "\n")
        return preview

    preview = check_preview(first_line, first_line)
    _, manifest_path = tab.save_to(tmp_path / f"{kind}-short.agf")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["materials"][0] == preview.manifest["materials"][0]
    # A repeated Add must not reset an existing item or invalidate its preview.
    item = tab.basket[material.identity]
    tab.add_selected()
    assert tab.basket[material.identity] is item and tab.preview is preview
    manual = "Manual first line\nManual second line"

    def save_manual(dialog):
        assert dialog.original.toPlainText() == original
        assert dialog.editor.toPlainText() == first_line
        dialog.editor.setPlainText(manual)
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(CommentDialog, "exec", save_manual)
    tab.edit_glass_comment()
    # Adding genuinely new rows must not reinitialize existing manual overrides.
    extra = parse_agf(imported_block("GC Added first\r\nGC Added second\r\n").replace(
        "NM IMPORTED ", "NM EXTRA "), source_path="extra.agf")
    tab.imported((tab.generation, [extra], []))
    tab.selected_ids = set(tab.materials)
    tab.add_selected()
    assert tab.basket[extra.materials[0].identity].glass_comment == "Added first"
    check_preview(manual, manual)

    def reset(dialog):
        assert dialog.editor.toPlainText() == manual
        dialog.reset_button.click()
        assert dialog.editor.toPlainText() == original
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(CommentDialog, "exec", reset)
    tab.edit_glass_comment()
    assert tab.basket[material.identity].glass_comment is None
    tab.add_selected()
    check_preview(original, None)
    if source_bytes is not None:
        assert source.read_bytes() == source_bytes
    else:
        assert glass.remarks == "Workbook first remark\nWorkbook second remark"
