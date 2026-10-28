"""Output-only naming/comment edits, draft semantics, and compact AGF controls."""
from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QDialogButtonBox, QStyle, QStyleOptionViewItem

from glass_workbench.catalogs.agf import parse_agf
from glass_workbench.catalogs.agf_export import DEFAULT_CATALOG_COMMENT, material_comment
from glass_workbench.contracts import Catalog, Glass
from glass_workbench.ui.agf import AgfTab, BasketModel, CommentDialog
from glass_workbench.ui.main_window import MainWindow


def block(name="A"):
    return (f"NM {name} 1 0 1.5 60 0 0\n"
            "GC Original glass comment\nCC Material CC must stay\n! Not GC\n"
            "CD 2.250000000000000000 0 0 0 0 0\nLD 0.4 0.7\n")


def tab_with(qtbot, text=None):
    tab = AgfTab()
    qtbot.addWidget(tab)
    document = parse_agf(text or "CC Original catalog header\n" + block(), source_path="original.agf")
    tab.imported((tab.generation, [document], []))
    tab.selected_ids = set(tab.materials)
    tab.add_selected()
    return tab, document


def select_basket(tab, identities):
    tab.basket_view.clearSelection()
    for row, record in enumerate(tab.basket_model.rows):
        if record["identity"] in identities:
            tab.basket_view.selectionModel().select(tab.basket_model.index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)


def dialog_action(monkeypatch, action, *, accepted):
    def execute(dialog):
        action(dialog)
        button = QDialogButtonBox.StandardButton.Save if accepted else QDialogButtonBox.StandardButton.Cancel
        dialog.buttons.button(button).click()
        return dialog.result()
    monkeypatch.setattr(CommentDialog, "exec", execute)


def test_auto_names_both_sources_reserve_valid_names_and_existing_overrides(qtbot):
    tab, document = tab_with(qtbot, block("H-K9L*") + block("H-K9L_ST"))
    identity = document.materials[0].identity
    assert tab.basket[identity].export_name == "H-K9L_ST_2"
    assert document.materials[0].name == "H-K9L*"
    tab.rename_item(identity, "USER_NAME")
    glass = Glass("CDGM", "USER/NAME", "500600", 1.5, 60, dispersion_model="polynomial",
                  dispersion=(2.25, 0, 0, 0, 0, 0), source_file="workbook.xlsx", source_sheet="First",
                  source_row=2, source_hash="v1", wavelength_range=(0.4, 0.7))
    tab.update_workbooks([Catalog("CDGM", "workbook.xlsx", "First", "v1", [glass])])
    tab.selected_ids = set(tab.materials)
    tab.add_selected()
    generated = next(item for item in tab.basket.values() if item.material.generated)
    assert generated.export_name == "USER_NAME_2"
    assert generated.material.name == glass.name == "USER/NAME"
    tab.set_global_filters(supplier="SCHOTT", search="absent")
    assert len(tab.basket) == 3
    assert tab.basket[identity].export_name == "USER_NAME"
    assert len(tab.source_model.rows) == 2  # Imported AGF bypasses global filters.
    tab.acknowledge.setChecked(True)
    assert tab.validate_export().valid


def test_red_alias_tooltip_and_selection_survive_stable_sort(qtbot):
    tab, document = tab_with(qtbot, block("Z*") + block("A"))
    identity = document.materials[0].identity
    select_basket(tab, {identity})
    assert isinstance(tab.basket_model, BasketModel)
    column = tab.basket_model.columns.index("export_name")
    for order in (Qt.SortOrder.AscendingOrder, Qt.SortOrder.DescendingOrder):
        tab.basket_view.sortByColumn(column, order)
        selected = tab.basket_view.selectionModel().selectedRows()
        assert [tab.basket_model.rows[i.row()]["identity"] for i in selected] == [identity]
        index = tab.basket_model.index(selected[0].row(), column)
        assert index.data(Qt.ItemDataRole.ForegroundRole) == QColor("#b71c1c")
        assert "Z* → Z_ST" in index.data(Qt.ItemDataRole.ToolTipRole)
        for background in ("#204080", "#eeeeee"):
            option = QStyleOptionViewItem()
            option.state |= QStyle.StateFlag.State_Selected
            option.palette.setColor(QPalette.ColorRole.Highlight, QColor(background))
            tab.basket_view.itemDelegate().initStyleOption(option, index)
            red = option.palette.color(QPalette.ColorRole.HighlightedText)
            assert red.red() > red.green() and red.red() > red.blue()
    plain_row = next(i for i, row in enumerate(tab.basket_model.rows) if row["original_name"] == "A")
    assert tab.basket_model.index(plain_row, column).data(Qt.ItemDataRole.ForegroundRole) is None
    tab.rename_item(identity, "Z*")
    index = tab.basket_model.index(tab.basket_view.selectionModel().selectedRows()[0].row(), column)
    assert index.data(Qt.ItemDataRole.ForegroundRole) is None


def test_valid_duplicate_names_and_source_diagnostics_still_block(qtbot):
    tab, _ = tab_with(qtbot, block("SAME") + block("same"))
    assert len(tab.basket) == 2
    assert not tab.validate_export().valid
    malformed = parse_agf(block("BAD*") + "ED malformed\n", source_path="bad.agf")
    tab.clear_basket()
    tab.imported((tab.generation, [malformed], []))
    identity = malformed.materials[0].identity
    tab.selected_ids = {identity}
    tab.add_selected()
    assert tab.basket[identity].export_name == "BAD_ST"
    assert not tab.validate_export().valid
    assert tab.basket[identity].material.diagnostics


def test_comment_cancel_and_selection_leave_preview_and_sources_unchanged(qtbot, monkeypatch):
    tab, document = tab_with(qtbot, block("A") + block("B"))
    identity = document.materials[0].identity
    before = tab.validate_export()
    assert before.valid
    select_basket(tab, {identity})
    assert tab.glass_comment_button.isEnabled()
    assert tab.preview is before
    original = tab.basket[identity]
    dialog_action(monkeypatch, lambda dialog: dialog.editor.setPlainText("Discard me"), accepted=False)
    tab.edit_glass_comment()
    assert tab.basket[identity] is original
    assert tab.preview is before and tab.export_button.isEnabled()
    select_basket(tab, set(tab.basket))
    assert not tab.glass_comment_button.isEnabled()
    tab.edit_glass_comment()
    assert "exactly one" in tab.status.text()
    assert tab.preview is before
    assert document.materials[0].raw_text == block("A")


def test_glass_save_empty_reset_and_rename_preserve_other_override(qtbot, monkeypatch):
    tab, document = tab_with(qtbot)
    identity = document.materials[0].identity
    select_basket(tab, {identity})
    tab.validate_export()
    dialog_action(monkeypatch, lambda dialog: dialog.editor.setPlainText("Edited 中文\nsecond line"), accepted=True)
    tab.edit_glass_comment()
    assert tab.preview is None and not tab.export_button.isEnabled()
    tab.rename_item(identity, "RENAMED")
    assert tab.basket[identity].glass_comment == "Edited 中文\nsecond line"
    assert tab.basket[identity].export_name == "RENAMED"
    assert '"effective_name": "RENAMED"' in tab.details.toPlainText()
    assert "Edited 中文" in tab.details.toPlainText()
    assert tab.raw.toPlainText() == block()
    preview = tab.validate_export()
    assert preview.valid and "GC Edited 中文" in preview.text
    dialog_action(monkeypatch, lambda dialog: dialog.editor.clear(), accepted=True)
    tab.edit_glass_comment()
    assert tab.basket[identity].glass_comment == ""
    assert tab.basket[identity].export_name == "RENAMED"
    preview = tab.validate_export()
    assert preview.valid
    assert not any(line.startswith("GC") for line in preview.text.splitlines())
    assert "CC Material CC must stay" in preview.text and "! Not GC" in preview.text
    dialog_action(monkeypatch, lambda dialog: dialog.reset_button.click(), accepted=True)
    tab.edit_glass_comment()
    assert tab.basket[identity].glass_comment is None
    assert tab.basket[identity].export_name == "RENAMED"
    preview = tab.validate_export()
    assert preview.valid and "GC Original glass comment" in preview.text
    assert document.materials[0].raw_text == block()


def test_untouched_glass_save_and_reset_cancel_preserve_override_state(qtbot, monkeypatch):
    tab, document = tab_with(qtbot)
    identity = document.materials[0].identity
    select_basket(tab, {identity})
    before = tab.validate_export()
    dialog_action(monkeypatch, lambda dialog: None, accepted=True)
    tab.edit_glass_comment()
    assert tab.basket[identity].glass_comment is None
    assert tab.preview is before
    tab.set_glass_comment(identity, "Previously saved")
    before = tab.validate_export()
    dialog_action(monkeypatch, lambda dialog: dialog.reset_button.click(), accepted=False)
    tab.edit_glass_comment()
    assert tab.basket[identity].glass_comment == "Previously saved"
    assert tab.preview is before


def test_dialog_original_gc_only_and_reset_draft(qtbot):
    material = parse_agf(block()).materials[0]
    dialog = CommentDialog("Glass", material_comment(material), "Override")
    qtbot.addWidget(dialog)
    assert dialog.original.isReadOnly()
    assert dialog.original.toPlainText() == "Original glass comment"
    assert dialog.editor.toPlainText() == "Override"
    dialog.reset_button.click()
    assert dialog.comment_value is None
    assert dialog.editor.toPlainText() == "Original glass comment"
    dialog.editor.clear()
    assert dialog.comment_value == ""


def test_catalog_comment_headers_save_cancel_and_empty(qtbot, monkeypatch):
    tab, first = tab_with(qtbot)
    second = parse_agf("CC Empty catalog header\n", source_path="empty.agf")
    tab.imported((tab.generation, [second], []))
    before = tab.validate_export()
    def check_and_change(dialog):
        assert dialog.original.isReadOnly()
        assert "original.agf" in dialog.original.toPlainText()
        assert "CC Original catalog header" in dialog.original.toPlainText()
        assert "empty.agf" in dialog.original.toPlainText()
        assert "CC Empty catalog header" in dialog.original.toPlainText()
        assert "Material CC must stay" not in dialog.original.toPlainText()
        assert dialog.editor.toPlainText() == DEFAULT_CATALOG_COMMENT
        dialog.editor.setPlainText("Combined catalog\nUnicode 中文")
    dialog_action(monkeypatch, check_and_change, accepted=False)
    tab.edit_catalog_comment()
    assert tab.catalog_comment == DEFAULT_CATALOG_COMMENT and tab.preview is before
    dialog_action(monkeypatch, check_and_change, accepted=True)
    tab.edit_catalog_comment()
    assert tab.preview is None and not tab.export_button.isEnabled()
    preview = tab.validate_export()
    assert preview.valid and "CC Combined catalog" in preview.text and "CC Unicode 中文" in preview.text
    assert first.header == "CC Original catalog header\n"
    assert second.header == "CC Empty catalog header\n"
    dialog_action(monkeypatch, lambda dialog: dialog.editor.clear(), accepted=True)
    tab.edit_catalog_comment()
    assert tab.catalog_comment == ""
    assert tab.validate_export().valid


def test_saved_export_comment_edits_never_modify_source_file(qtbot, tmp_path):
    source = tmp_path / "source.agf"
    source.write_bytes(("CC Header\r\n" + block()).encode("utf-8"))
    original_bytes = source.read_bytes()
    document = parse_agf(original_bytes.decode("utf-8"), source_path=source)
    tab = AgfTab()
    qtbot.addWidget(tab)
    tab.imported((tab.generation, [document], []))
    identity = document.materials[0].identity
    tab.selected_ids = {identity}
    tab.add_selected()
    tab.set_glass_comment(identity, "New glass")
    tab.rename_item(identity, "NEW_NAME")
    tab.catalog_comment = "New catalog"
    preview = tab.validate_export()
    assert preview.valid
    tab.save_to(tmp_path / "output.agf")
    assert source.read_bytes() == original_bytes
    assert tab.basket[identity].material is document.materials[0]


def test_controls_fit_minimum_window_without_wide_action_rows(qtbot):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    tab = window.agf
    document = parse_agf("".join(block(f"G{i}") for i in range(12)))
    tab.imported((tab.generation, [document], []))
    tab.selected_ids = set(tab.materials)
    tab.add_selected()
    window.tabs.setCurrentWidget(tab)
    window.resize(1060, 720)
    window.show()
    qtbot.wait(50)
    assert tab.minimumSizeHint().width() <= 1060
    assert window.width() == 1060 and window.height() == 720
    assert tab.source_view.height() >= 100 and tab.basket_view.height() >= 100
    for button in (tab.add_button, tab.rename_button, tab.glass_comment_button,
                   tab.catalog_comment_button, tab.validate_button, tab.export_button):
        tab.scroll_area.ensureWidgetVisible(button)
        qtbot.wait(10)
        assert button.isVisible()
        position = button.mapTo(tab, button.rect().topLeft())
        assert position.x() >= 0 and position.x() + button.width() <= tab.width()
        assert position.y() >= 0 and position.y() + button.height() <= tab.height()
    window.resize(1480, 980)
    qtbot.wait(50)
    assert tab.scroll_area.verticalScrollBar().maximum() == 0
    assert tab.export_button.mapTo(tab, tab.export_button.rect().bottomRight()).y() < tab.height()


def test_selected_alias_pixels_are_red_under_application_stylesheet(qtbot):
    window = MainWindow(auto_load=False)
    qtbot.addWidget(window)
    tab = window.agf
    document = parse_agf(block("H-K9L*") + block("PLAIN"))
    tab.imported((tab.generation, [document], []))
    tab.selected_ids = set(tab.materials)
    tab.add_selected()
    window.tabs.setCurrentWidget(tab)
    window.show()
    select_basket(tab, {document.materials[0].identity})
    tab.basket_view.setFocus()
    qtbot.wait(50)
    row = tab.basket_view.selectionModel().selectedRows()[0].row()
    index = tab.basket_model.index(row, tab.basket_model.columns.index("export_name"))
    rect = tab.basket_view.visualRect(index)
    image = tab.basket_view.viewport().grab(rect).toImage()
    red_pixels = sum(1 for x in range(image.width()) for y in range(image.height())
                     if (color := image.pixelColor(x, y)).red() > color.green() + 25
                     and color.red() > color.blue() + 25)
    assert red_pixels > 20, "Selected alias must render red, not native selected-text white"
