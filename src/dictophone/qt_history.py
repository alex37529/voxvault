from __future__ import annotations

from typing import Callable

from PySide6 import QtWidgets

from dictophone import storage


class HistoryDialog(QtWidgets.QDialog):
    def __init__(self, tr: Callable[..., str], db: storage.Storage, parent=None):
        super().__init__(parent)
        self._t = tr
        self._db = db
        self._rows: list[dict] = []
        self.setWindowTitle(self._t("history.title"))
        self.setMinimumSize(900, 600)

        root = QtWidgets.QVBoxLayout(self)
        tools = QtWidgets.QHBoxLayout()
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText(self._t("history.search"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._refresh)
        self.search_btn = QtWidgets.QPushButton(self._t("history.find"))
        self.search_btn.clicked.connect(self._refresh)
        self.all_btn = QtWidgets.QPushButton(self._t("history.show_all"))
        self.all_btn.clicked.connect(self._show_all)
        tools.addWidget(self.search_edit)
        tools.addWidget(self.search_btn)
        tools.addWidget(self.all_btn)
        tools.addStretch(1)
        root.addLayout(tools)

        self.table = QtWidgets.QTableWidget(0, 6, self)
        self.table.setHorizontalHeaderLabels([
            self._t("history.id"),
            self._t("history.when"),
            self._t("history.kind"),
            self._t("history.lang"),
            self._t("history.duration"),
            self._t("history.preview"),
        ])
        self.table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.table.currentCellChanged.connect(self._show_selected)
        root.addWidget(self.table, 1)

        self.details = QtWidgets.QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setPlaceholderText(self._t("history.details_placeholder"))
        root.addWidget(self.details, 1)

        buttons = QtWidgets.QDialogButtonBox()
        self.copy_btn = buttons.addButton(
            self._t("history.copy"), QtWidgets.QDialogButtonBox.ButtonRole.ActionRole
        )
        self.copy_btn.clicked.connect(self._copy)
        self.delete_btn = buttons.addButton(
            self._t("history.delete"), QtWidgets.QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.delete_btn.clicked.connect(self._delete)
        self.clear_btn = buttons.addButton(
            self._t("history.clear"), QtWidgets.QDialogButtonBox.ButtonRole.DestructiveRole
        )
        self.clear_btn.clicked.connect(self._clear)
        close_btn = buttons.addButton(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        close_btn.clicked.connect(self.reject)
        root.addWidget(buttons)
        self._show_all()

    def _fill(self, rows: list[dict]) -> None:
        self._rows = rows
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            kind = self._t("history.kind_mic") if row.get("kind") == "mic" else self._t("history.kind_file")
            preview = (row.get("text") or "").replace("\n", " ").strip()
            values = [
                str(row.get("id", "")),
                (row.get("created_at") or "")[:16].replace("T", " "),
                kind,
                row.get("lang") or "?",
                f"{row.get('audio_s') or 0:.1f} s",
                preview,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QtWidgets.QTableWidgetItem(str(value)))
        if rows:
            self.table.selectRow(0)
            self._show_selected(0, 0, -1, -1)
        else:
            self.details.clear()

    def _refresh(self) -> None:
        query = self.search_edit.text().strip()
        rows = self._db.search(query, limit=500) if query else self._db.list(limit=500)
        self._fill(rows)

    def _show_all(self) -> None:
        self.search_edit.clear()
        self._fill(self._db.list(limit=500))

    def _current_entry(self) -> dict | None:
        row_index = self.table.currentRow()
        if row_index < 0 or row_index >= len(self._rows):
            return None
        entry_id = self._rows[row_index].get("id")
        return self._db.get(int(entry_id)) if entry_id is not None else None

    def _show_selected(self, *_args) -> None:
        entry = self._current_entry()
        if entry is None:
            self.details.clear()
            return
        self.details.setPlainText(entry.get("text") or "")

    def _copy(self) -> None:
        text = self.details.toPlainText()
        if text:
            QtWidgets.QApplication.clipboard().setText(text)

    def _delete(self) -> None:
        entry = self._current_entry()
        if entry is None:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self._t("history.delete"),
            self._t("history.confirm_delete", entry_id=entry["id"]),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self._db.delete(int(entry["id"]))
            self._refresh()

    def _clear(self) -> None:
        total = self._db.count()
        if not total:
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            self._t("history.clear"),
            self._t("history.confirm_clear", count=total),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            self._db.clear()
            self._fill([])
