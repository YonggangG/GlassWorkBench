import json
import threading

from dataclasses import replace

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox

from glass_workbench.catalogs.agf import parse_agf
from glass_workbench.contracts import Catalog, Glass
from glass_workbench.ui.agf import AgfTab
from glass_workbench.ui.main_window import MainWindow


def block(name="A", formula=1):
    return (f"NM {name} {formula} 0 1.5 60 0 0\n"
            "GC Original precision retained\n"
            "CD 2.250000000000000000 0 0 0 0 0 0 0 0 0\n"
            "LD 0.4 0.7\nIT 0.5 0.99 10\n")


def tab_with(qtbot, text=None, path="one.agf"):
    tab = AgfTab()
    qtbot.addWidget(tab)
    doc = parse_agf(text or block(), source_path=path)
    tab.imported((tab.generation, [doc], []))
    return tab, doc


def select_ids(tab, identities):
    tab.clear_selection()
    for row, record in enumerate(tab.source_model.rows):
        if record["identity"] in identities:
            tab.source_view.selectionModel().select(tab.source_model.index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)


def workbook(name="WORK", digest="v1", coefficient=2.25, path="catalog.xlsx"):
    glass = Glass("CDGM", name, "500600", 1.5, 60, dispersion_model="polynomial",
                  dispersion=(coefficient, 0, 0, 0, 0, 0), source_file=path,
                  source_sheet="First", source_row=2, source_hash=digest,
                  wavelength_range=(0.4, 0.7))
    return Catalog("CDGM", path, "First", digest, [glass])


def test_import_partial_failure_keeps_previous_sources(qtbot, tmp_path):
    tab, original = tab_with(qtbot)
    good = tmp_path / "good.agf"
    good.write_text(block("GOOD"))
    missing = tmp_path / "missing.agf"
    assert tab.load_paths([good, missing])
    qtbot.waitUntil(lambda: not tab.job.busy, timeout=5000)
    assert {m.name for m in tab.materials.values()} == {"A", "GOOD"}
    assert original.materials[0].identity in tab.materials
    assert "1 failed" in tab.status.text()
    assert "missing.agf" in tab.status.text()
    assert str(missing.resolve()) in tab.protected_paths


def test_multiselection_survives_sort_and_hidden_filter(qtbot):
    tab, document = tab_with(qtbot, block("Z") + block("A") + block("M"))
    ids = {document.materials[0].identity, document.materials[1].identity}
    select_ids(tab, ids)
    tab.source_view.sortByColumn(tab.source_model.columns.index("name"), Qt.SortOrder.AscendingOrder)
    assert {tab.source_model.rows[i.row()]["identity"] for i in tab.source_view.selectionModel().selectedRows()} == ids
    tab.search.setText("Z")
    assert tab.selected_ids == ids
    assert "1 hidden" in tab.selection_label.text()
    tab.add_selected()
    tab.add_selected()
    assert set(tab.basket) == ids
    tab.search.clear()
    assert len(tab.source_view.selectionModel().selectedRows()) == 2
    assert tab.source_model.rows[0]["name"] == "A"


def test_local_source_formula_filter_keeps_unsupported_material(qtbot):
    tab, first = tab_with(qtbot, block("UNKNOWN", 99))
    second = parse_agf(block("KNOWN"), source_path="two.agf")
    tab.imported((tab.generation, [second], []))
    assert len(tab.materials) == 2
    tab.set_global_filters(supplier="SCHOTT", melt="MA", search="nonexistent")
    assert len(tab.source_model.rows) == 2
    tab.formula_filter.setCurrentIndex(tab.formula_filter.findData("99"))
    assert [row["name"] for row in tab.source_model.rows] == ["UNKNOWN"]
    tab.source_view.selectRow(0)
    assert "99" in tab.details.toPlainText()
    assert "2.250000000000000000" in tab.raw.toPlainText()
    tab.add_selected()
    assert first.materials[0].identity in tab.basket
    tab.formula_filter.setCurrentIndex(0)
    tab.source_filter.setCurrentIndex(tab.source_filter.findData(tab.material_sources[second.materials[0].identity]))
    assert [row["name"] for row in tab.source_model.rows] == ["KNOWN"]
    assert len(tab.basket) == 1


def test_collision_rename_preview_save_and_source_protection(qtbot, tmp_path):
    source = tmp_path / "original.agf"
    source.write_text(block())
    tab, first = tab_with(qtbot, path=str(source))
    other_path = tmp_path / "unselected.agf"
    other_path.write_text(block())
    second = parse_agf(block(), source_path=str(other_path))
    tab.imported((tab.generation, [second], []))
    tab.selected_ids = set(tab.materials)
    tab.add_selected()
    assert not tab.validate_export().valid
    assert not tab.export_button.isEnabled()
    tab.rename_item(second.materials[0].identity, "RENAMED")
    preview = tab.validate_export()
    assert preview.valid, preview.errors
    assert "NM RENAMED " in preview.text
    assert tab.preview_text.toPlainText().replace("\n", "") == preview.text.replace("\r", "").replace("\n", "")
    output = tmp_path / "new.agf"
    paths = tab.save_to(output)
    assert len(paths) == 2
    assert output.read_text(encoding="utf-16").replace("\n", "") == preview.text.replace("\r", "").replace("\n", "")
    assert json.loads(output.with_suffix(".metadata.json").read_text(encoding="utf-8"))
    with pytest.raises(FileExistsError):
        tab.save_to(output)
    tab.clear_basket()
    tab.selected_ids = {first.materials[0].identity}
    tab.add_selected()
    assert tab.validate_export().valid
    with pytest.raises(ValueError):
        tab.save_to(other_path, overwrite=True)
    assert other_path.read_text() == block()


def test_preview_invalidates_on_rename_remove_and_options(qtbot):
    tab, doc = tab_with(qtbot)
    tab.selected_ids = {doc.materials[0].identity}
    tab.add_selected()
    assert tab.validate_export().valid
    tab.acknowledge.setChecked(True)
    assert tab.preview is None
    assert not tab.export_button.isEnabled()
    assert not tab.preview_text.toPlainText()
    tab.validate_export()
    tab.rename_item(doc.materials[0].identity, "RENAMED")
    assert tab.preview is None
    tab.basket_view.selectRow(0)
    tab.remove_selected()
    assert not tab.basket
    with pytest.raises(ValueError):
        tab.save_to("never-created.agf")


def test_archival_controls_default_off_and_explicit(qtbot):
    tab, doc = tab_with(qtbot, block() + "ED not-a-number\n")
    assert not tab.acknowledge.isChecked()
    assert not tab.preserve_invalid.isChecked()
    tab.selected_ids = {doc.materials[0].identity}
    tab.add_selected()
    assert not tab.validate_export().valid
    tab.preserve_invalid.setChecked(True)
    preview = tab.validate_export()
    assert preview.valid, preview.errors
    assert "ED not-a-number" in preview.text
    assert preview.warnings


def test_workbook_reload_keeps_basket_snapshot_and_unfiltered_population(qtbot, tmp_path):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    path = str(tmp_path / "source.xlsx")
    window.imported(([workbook(path=path)], []))
    tab = window.agf
    assert len(tab.materials) == 1
    identity = next(iter(tab.materials))
    tab.selected_ids = {identity}
    tab.add_selected()
    old_material = tab.basket[identity].material
    window.search.setText("nothing")
    window.apply_filters()
    assert not tab.source_model.rows
    assert not tab.selected_ids
    window.imported(([workbook(digest="v2", coefficient=2.56, path=path)], []))
    assert len(tab.materials) == 2
    assert len(window.catalogs["CDGM"].glasses) == 1
    assert tab.basket[identity].material is old_material
    assert "2.25" in old_material.raw_text
    assert str(tmp_path / "source.xlsx") in tab.protected_paths
    window.close()


def test_failed_and_superseded_workbook_paths_remain_protected(qtbot, tmp_path):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    first = tmp_path / "first.xlsx"
    second = tmp_path / "second.xlsx"
    failed = tmp_path / "failed.xlsx"
    window.imported(([workbook(path=str(first))], []))
    window.imported(([workbook(path=str(second), digest="v2")], []))
    window.load_paths([failed])
    qtbot.waitUntil(lambda: not window.import_job.busy, timeout=5000)
    assert {str(p.resolve()) for p in (first, second, failed)} <= window.agf.protected_paths
    assert window.catalogs["CDGM"].path == str(second)
    window.close()


def test_agf_import_does_not_change_calculation_population(qtbot):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    before = tuple(window.glasses)
    window.agf.imported((window.agf.generation, [parse_agf(block())], []))
    assert tuple(window.glasses) == before
    assert window.tabs.tabText(5) == "AGF Catalogs"
    window.close()


def test_cancel_discards_stale_import_results(qtbot, monkeypatch, tmp_path):
    tab = AgfTab()
    qtbot.addWidget(tab)
    started, release = threading.Event(), threading.Event()
    doc = parse_agf(block())

    def slow_load(*args, **kwargs):
        started.set()
        release.wait(3)
        return doc

    monkeypatch.setattr("glass_workbench.ui.agf.load_agf", slow_load)
    tab.load_paths([tmp_path / "slow.agf"])
    qtbot.waitUntil(started.is_set, timeout=3000)
    tab.cancel_import()
    release.set()
    qtbot.waitUntil(lambda: not tab.job.busy, timeout=5000)
    assert not tab.materials
    assert "cancelled" in tab.status.text()


def test_window_close_waits_and_discards_pending_agf_import(qtbot, monkeypatch, tmp_path):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    window.show()
    started, release = threading.Event(), threading.Event()

    def slow_load(*args, **kwargs):
        started.set()
        release.wait(3)
        return parse_agf(block())

    monkeypatch.setattr("glass_workbench.ui.agf.load_agf", slow_load)
    window.agf.load_paths([tmp_path / "slow.agf"])
    qtbot.waitUntil(started.is_set, timeout=3000)
    window.close()
    assert window.closing
    release.set()
    qtbot.waitUntil(lambda: not window.agf.job.busy, timeout=5000)
    qtbot.waitUntil(lambda: not window.isVisible(), timeout=5000)
    assert not window.agf.materials


def test_save_dialog_confirms_both_existing_targets(qtbot, monkeypatch, tmp_path):
    tab, doc = tab_with(qtbot)
    tab.selected_ids = {doc.materials[0].identity}
    tab.add_selected()
    assert tab.validate_export().valid
    target = tmp_path / "new.agf"
    metadata = target.with_suffix(".metadata.json")
    target.write_bytes(b"old")
    metadata.write_bytes(b"old metadata")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    prompts = []

    def deny(*args):
        prompts.append(args[2])
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", deny)
    tab.export_dialog()
    assert str(target) in prompts[0] and str(metadata) in prompts[0]
    assert target.read_bytes() == b"old"
    assert metadata.read_bytes() == b"old metadata"
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    tab.export_dialog()
    assert target.read_bytes().startswith(b"\xff\xfe")
    assert json.loads(metadata.read_text(encoding="utf-8"))


def test_large_import_report_does_not_hide_tables(qtbot):
    tab, _ = tab_with(qtbot, "".join(block(f"G{i}") + "ED malformed\n" for i in range(100)))
    tab.resize(1300, 800)
    tab.show()
    qtbot.wait(50)
    assert tab.status.height() <= 56
    assert tab.source_view.height() > 100
    assert "100 / 100 materials" in tab.selection_label.text()
    assert "ED" in tab.diagnostics.toPlainText()
    assert len(tab.status.text()) < 500


def test_generated_warning_ack_and_invalid_dispersion_cannot_be_bypassed(qtbot):
    tab = AgfTab()
    qtbot.addWidget(tab)
    catalog = workbook()
    tab.update_workbooks([catalog])
    tab.selected_ids = set(tab.materials)
    tab.add_selected()
    assert not tab.validate_export().valid
    tab.acknowledge.setChecked(True)
    preview = tab.validate_export()
    assert preview.valid, preview.errors
    assert preview.warnings
    bad = replace(catalog.glasses[0], source_hash="bad", dispersion=())
    tab.update_workbooks([Catalog("CDGM", "bad.xlsx", "First", "bad", [bad])])
    tab.selected_ids = set(tab.materials)
    tab.add_selected()
    assert not tab.acknowledge.isChecked()
    tab.acknowledge.setChecked(True)
    tab.preserve_invalid.setChecked(True)
    assert not tab.validate_export().valid


def test_save_dialog_reports_partial_write(qtbot, monkeypatch, tmp_path):
    tab, doc = tab_with(qtbot)
    tab.selected_ids = {doc.materials[0].identity}
    tab.add_selected()
    assert tab.validate_export().valid
    target = tmp_path / "new.agf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))

    class PartialFailure(OSError):
        written_paths = (target,)

    def fail(*args, **kwargs):
        raise PartialFailure("manifest unavailable")

    messages = []
    monkeypatch.setattr("glass_workbench.ui.agf.write_export", fail)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: messages.append(a[2]))
    tab.export_dialog()
    assert "already replaced" in messages[0]
    assert str(target) in messages[0]
