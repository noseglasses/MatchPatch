from __future__ import annotations

from matchpatch.normalize import DEFAULT_REFERENCE_DI
from matchpatch.runtime_resources import REFERENCE_DI_NAME, resource_path


def test_default_reference_di_resolves_to_existing_runtime_resource() -> None:
    assert DEFAULT_REFERENCE_DI.name == REFERENCE_DI_NAME
    assert DEFAULT_REFERENCE_DI.is_file()


def test_gui_brand_assets_resolve_to_existing_runtime_resources() -> None:
    assert resource_path("docs", "assets", "matchmatch-icon.png").is_file()
    assert resource_path("docs", "assets", "matchmatch-icon-512.png").is_file()
    assert resource_path("docs", "assets", "matchmatch-logo.png").is_file()
