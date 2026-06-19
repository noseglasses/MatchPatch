from __future__ import annotations

from unittest.mock import Mock

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from matchpatch.gui.main_window import MainWindow


def test_closing_main_window_is_ignored_when_cancellation_is_declined(monkeypatch, app) -> None:
    window = MainWindow()
    worker = Mock()
    window.worker = worker
    quit_requests = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    monkeypatch.setattr(QApplication, "quit", lambda: quit_requests.append(True))
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()
    worker.cancel.assert_not_called()
    assert quit_requests == []

    window.worker = None
    window.close()


def test_closing_main_window_cancels_measurement_when_confirmation_is_accepted(
    monkeypatch, app
) -> None:
    window = MainWindow()
    worker = Mock()
    window.worker = worker
    quit_requests = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QApplication, "quit", lambda: quit_requests.append(True))
    event = QCloseEvent()

    window.closeEvent(event)

    assert event.isAccepted()
    worker.cancel.assert_called_once_with()
    assert quit_requests == [True]


def test_closing_main_window_explicitly_quits_application(monkeypatch, app) -> None:
    window = MainWindow()
    quit_requests = []
    monkeypatch.setattr(QApplication, "quit", lambda: quit_requests.append(True))

    window.close()

    assert quit_requests == [True]
