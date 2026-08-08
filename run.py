"""PyInstaller entry point for the desktop application.

Kept at the repository root so ``scripts/build_release.py`` has a stable script
to bundle; running ``python run.py`` is equivalent to ``python -m transrealm.ui``.
"""

from transrealm.ui.main_window import main  # type: ignore[import-untyped]

if __name__ == "__main__":
    main()
