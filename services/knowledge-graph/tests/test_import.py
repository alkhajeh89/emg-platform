import importlib


def test_package_modules_import() -> None:
    pkg = importlib.import_module("emg_knowledge_graph")
    assert importlib.import_module("emg_knowledge_graph.service")
    assert importlib.import_module("emg_knowledge_graph.commands")
    assert importlib.import_module("emg_knowledge_graph.errors")
    assert hasattr(pkg, "KnowledgeGraphApplication")
