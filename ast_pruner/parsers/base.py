from __future__ import annotations

from abc import ABC, abstractmethod

from ast_pruner.models import ParsedFile


class BaseParser(ABC):
    @abstractmethod
    def parse(self, abs_path: str) -> ParsedFile:
        """Parse a source file and return structured symbol/import data."""
        ...
