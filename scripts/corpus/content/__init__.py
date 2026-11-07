# SPDX-License-Identifier: Apache-2.0

"""Corpus content: one module per department folder, each exporting DOCS."""

from __future__ import annotations

import importlib
import pkgutil

from model import Doc


def load_docs() -> list[Doc]:
    docs: list[Doc] = []
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        docs.extend(getattr(module, "DOCS", []))
    return docs
