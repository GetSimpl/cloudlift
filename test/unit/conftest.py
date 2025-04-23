import os

import boto3
import pytest
from moto import mock_aws as moto_mock_aws


def pytest_addoption(parser):
    parser.addoption(
        "--keep-resources",
        action="store_true",
        default=False,
        help="my option: type1 or type2",
    )


@pytest.fixture
def keep_resources(request):
    """
    Presence of `keep_resources` retains the AWS resources created by cloudformation
    during the test run. By default, the resources are deleted after the run.
    """
    return request.config.getoption("--keep-resources")


@pytest.fixture(scope="module", autouse=True)
def test_aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "ap-south-1"


@pytest.fixture
def mock_aws(test_aws_credentials):
    """
    Mock all AWS interactions
    """
    with moto_mock_aws():
        yield


@pytest.fixture(scope="module")
def mock_aws_module_scoped(test_aws_credentials):
    """
    Mock all AWS interactions
    """
    with moto_mock_aws():
        yield


@pytest.fixture
def mocked_sts_client(mock_aws):
    yield boto3.client("sts")


@pytest.fixture
def fast_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda x: None)
    monkeypatch.setattr("cloudlift.config.dynamodb_configuration.sleep", lambda x: None)


def get_default_region():
    return os.environ.get("AWS_DEFAULT_REGION", "ap-south-1")


@pytest.fixture
def mock_get_region_for_environment(request, monkeypatch):
    """
    Mock for cloudlift.config.region.get_region_for_environment.

    This fixture patches the function `get_region_for_environment` to return a provided region
    if specified. If no region is provided, it defaults to the `AWS_DEFAULT_REGION` environment
    variable or "ap-south-1" if the variable is not set.

    Usage:
    - By default, it returns the environment variable `AWS_DEFAULT_REGION` or "ap-south-1".
    - Can be parameterized to return a custom region using `pytest.mark.parameterize`.

    Example:
        @pytest.mark.parameterize("mock_get_region_for_environment", ["us-west-2"], indirect=True)
        def test_example(mock_get_region_for_environment):
            assert mock_get_region_for_environment == "us-west-2"
    """
    region = getattr(request, "param", None) or get_default_region()
    monkeypatch.setattr(
        "cloudlift.config.region.get_region_for_environment",
        lambda x: region,
    )
    monkeypatch.setattr(
        "cloudlift.deployment.cluster_template_generator.get_region_for_environment",
        lambda x: region,
    )


@pytest.fixture
def mock_get_notifications_arn_for_environment(request, monkeypatch):
    """
    Mock for cloudlift.config.region.get_notifications_arn_for_environment
    """
    sns_topic_arn = getattr(request, "param", None)  # Get the param if provided
    if not sns_topic_arn:
        region = get_default_region()
        sns_topic_arn = f"arn:aws:sns:{region}:123456789012:test-notifications"
    monkeypatch.setattr(
        "cloudlift.config.region.get_notifications_arn_for_environment",
        lambda x: sns_topic_arn,
    )


@pytest.fixture
def mock_get_ssl_certification_for_environment(request, monkeypatch):
    """
    Mock for cloudlift.config.region.get_ssl_certification_for_environment
    """
    acm_arn = getattr(request, "param", None)  # Get the param if provided
    if not acm_arn:
        region = get_default_region()
        acm_arn = f"arn:aws:acm:{region}:123456789012:certificate/test-cert"
    monkeypatch.setattr(
        "cloudlift.config.region.get_ssl_certification_for_environment",
        lambda x: acm_arn,
    )
