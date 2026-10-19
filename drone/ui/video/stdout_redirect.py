"""Reindirizza l'output testuale verso la dashboard mantenendo compatibilità con stdout."""

from __future__ import annotations

from typing import Callable


class StdoutRedirect:
    """Adattatore file-like che inoltra le righe di stdout al pannello terminale."""
    def __init__(
        self,
        original,
        line_sink: Callable[[str], None],
        echo_to_original: bool = True,
    ):
        self._original = original
        self._line_sink = line_sink
        self._echo_to_original = bool(echo_to_original)
        self._pending = ""

    def write(self, text) -> int:
        """Inoltra il testo scritto al callback della dashboard."""
        if self._echo_to_original:
            try:
                self._original.write(text)
            except UnicodeEncodeError:
                enc = getattr(self._original, "encoding", None) or "utf-8"
                self._original.write(text.encode(enc, "replace").decode(enc))
        if not isinstance(text, str):
            text = str(text)
        self._pending += text
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            try:
                self._line_sink(line)
            except Exception:
                pass
        return len(text)

    def flush(self) -> None:
        """Mantiene compatibilità con l'interfaccia file-like di stdout."""
        self._original.flush()

    def __getattr__(self, name):
        return getattr(self._original, name)
