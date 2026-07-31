import importlib


def test_package_modules_import() -> None:
    pkg = importlib.import_module("emg_knowledge_graph")
    assert importlib.import_module("emg_knowledge_graph.service")
    assert importlib.import_module("emg_knowledge_graph.commands")
    assert importlib.import_module("emg_knowledge_graph.errors")
    assert importlib.import_module("emg_knowledge_graph.fingerprint")
    assert importlib.import_module("emg_knowledge_graph.results")
    assert importlib.import_module("emg_knowledge_graph.atomic_mutation")
    assert importlib.import_module("emg_knowledge_graph_infrastructure")
    assert hasattr(pkg, "BuildRevisionCommand")
    assert hasattr(pkg, "BuildRevisionResult")
    assert hasattr(pkg, "KnowledgeGraphApplication")
