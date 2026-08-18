import dataset_registry


def test_version():
    assert isinstance(dataset_registry.__version__, str)
