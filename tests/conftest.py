import pytest


@pytest.fixture(autouse=True, scope="session")
def _poucas_threads():
    """O gradient boosting em dados minúsculos perde mais tempo em OpenMP do que treinando."""
    try:
        from threadpoolctl import threadpool_limits
    except ImportError:
        yield
        return
    with threadpool_limits(limits=2):
        yield
