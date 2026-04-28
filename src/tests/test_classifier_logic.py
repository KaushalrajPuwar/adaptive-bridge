from adaptive_bridge import classifier_node


def test_classifier_module_imports() -> None:
    assert classifier_node is not None


def test_classifier_has_main_callable() -> None:
    assert callable(classifier_node.main)
