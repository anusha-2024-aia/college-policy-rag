"""Streamlit user interface package for Document RAG."""

import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
_ui_dir = str(Path(__file__).resolve().parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
while _ui_dir in sys.path:
    sys.path.remove(_ui_dir)
