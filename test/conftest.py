import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--keep-resources", action="store_true", default=False, help="my option: type1 or type2"
    )


@pytest.fixture
def keep_resources(request):
    """
    Presence of `keep_resources` retains the AWS resources created by cloudformation
    during the test run. By default, the resources are deleted after the run.
    """
    return request.config.getoption("--keep-resources")