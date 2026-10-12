from rag_common import hello


def test_hello_names_the_package() -> None:
    assert "rag-common" in hello()
