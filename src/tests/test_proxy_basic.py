from adaptive_bridge.proxy_node import ProxyNode, main


def test_proxy_module_imports() -> None:
    assert ProxyNode is not None


def test_proxy_has_main_callable() -> None:
    assert callable(main)
