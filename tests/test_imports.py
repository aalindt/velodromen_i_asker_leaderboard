def test_import_src_app():
    """Smoke test: importing src.app should expose a callable `main` function."""
    import importlib

    mod = importlib.import_module("src.app")
    assert hasattr(mod, "main"), "src.app should define a `main` function"
    assert callable(mod.main), "src.app.main should be callable"
