import copy
from unittest.mock import MagicMock

import boto3
import pytest
from botocore.exceptions import ClientError

from cloudlift.config.diff import print_json_changes
from cloudlift.config.environment_configuration import EnvironmentConfiguration
from cloudlift.config.service_configuration import ServiceConfiguration
from cloudlift.constants import FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
from cloudlift.exceptions import UnrecoverableException
from cloudlift.version import VERSION
from test.utils.helpers import flatten_dict

SERVICE_NAME = "test-service"
ENVIRONMENT_NAME = "test-environment"
SNS_TOPIC_NAME = "sns-topic"
SNS_TOPIC_ARN = f"arn:aws:sns:ap-south-1:123456789012:{SNS_TOPIC_NAME}"

CPU_MIN_VALUE = 128
CPU_MID_VALUE = 512
CPU_MAX_VALUE = 4096


@pytest.fixture
def dummy_environment_config():
    return {
        ENVIRONMENT_NAME: {
            "environment": {
                "notifications_arn": SNS_TOPIC_ARN,
                "ssl_certificate_arn": "arn:aws:acm:ap-south-1:123456789012:certificate/abcd",
            },
            "cluster": {
                "ami_id": "ami-id",
                "ecs_instance_default_lifecycle_type": "ondemand",
                "instance_type": "t2.micro",
                "key_name": ENVIRONMENT_NAME,
                "max_instances": 1,
                "min_instances": 1,
                "spot_allocation_strategy": "capacity-optimized",
                "spot_max_instances": 1,
                "spot_min_instances": 1,
            },
            "region": "ap-south-1",
            "service_defaults": {
                "alb_mode": "cluster",
                "disable_service_alarms": True,
                "fluentbit_config": {
                    "env": {"kinesis_role_arn": ""},
                    "image_uri": "123456789012.dkr.ecr.ap-south-1.amazonaws.com/fluentbit-repo:latest",
                    "memory_reservation": 100,
                },
                "logging": "awsfirelens",
            },
            "vpc": {
                "cidr": "10.100.0.0/16",
                "nat-gateway": {"elastic-ip-allocation-id": "eipalloc-abcd"},
                "subnets": {
                    "private": {
                        "subnet-1": {"cidr": "10.100.8.0/22"},
                        "subnet-2": {"cidr": "10.100.12.0/22"},
                    },
                    "public": {
                        "subnet-1": {"cidr": "10.100.0.0/22"},
                        "subnet-2": {"cidr": "10.100.4.0/22"},
                    },
                },
            },
        },
    }


@pytest.fixture
def dummy_service_config():
    return {
        "notifications_arn": SNS_TOPIC_ARN,
        "services": {
            "ClusterInternalECThree": {
                "command": None,
                "http_interface": {
                    "alb_mode": "cluster",
                    "container_port": 80,
                    "health_check_path": "/",
                    "hostnames": [
                        "cluster-internal-ec2-1.stagingsimpl.com",
                        "cluster-internal-ec2-2.stagingsimpl.com",
                    ],
                    "internal": True,
                    "restrict_access_to": ["0.0.0.0/0"],
                },
                "logging": None,
                "memory_reservation": 100,
                "spot_deployment": True,
            },
            "ClusterInternalFargateThree": {
                "command": None,
                "fargate": {"cpu": 256, "memory": 512},
                "http_interface": {
                    "alb_mode": "cluster",
                    "container_port": 80,
                    "health_check_path": "/",
                    "hostnames": [
                        "cluster-internal-fargate-1.stagingsimpl.com",
                        "cluster-internal-fargate-2.stagingsimpl.com",
                    ],
                    "internal": True,
                    "restrict_access_to": ["0.0.0.0/0"],
                },
                "logging": "awsfirelens",
                "memory_reservation": 100,
            },
            "ClusterPublicECOne": {
                "command": None,
                "http_interface": {
                    "alb_mode": "cluster",
                    "container_port": 80,
                    "health_check_path": "/",
                    "hostnames": [
                        "cluster-public-ec2-1.stagingsimpl.com",
                        "cluster-public-ec2-2.stagingsimpl.com",
                    ],
                    "internal": False,
                    "restrict_access_to": ["0.0.0.0/0"],
                },
                "logging": "awsfirelens",
                "memory_reservation": 100,
            },
            "ClusterPublicFargateOne": {
                "command": None,
                "fargate": {"cpu": 256, "memory": 512},
                "http_interface": {
                    "alb_mode": "cluster",
                    "container_port": 80,
                    "health_check_path": "/",
                    "hostnames": [
                        "cluster-public-fargate-1.stagingsimpl.com",
                        "cluster-public-fargate-2.stagingsimpl.com",
                    ],
                    "internal": False,
                    "restrict_access_to": ["0.0.0.0/0"],
                },
                "logging": "awsfirelens",
                "memory_reservation": 100,
            },
            "DedicatedInternalECFour": {
                "command": None,
                "http_interface": {
                    "alb_mode": "cluster",
                    "container_port": 80,
                    "health_check_path": "/",
                    "hostnames": [
                        "dedicated-internal-ec2-1.stagingsimpl.com",
                        "dedicated-internal-ec2-2.stagingsimpl.com",
                    ],
                    "internal": True,
                    "restrict_access_to": ["0.0.0.0/0"],
                },
                "logging": "awsfirelens",
                "memory_reservation": 100,
                "spot_deployment": True,
            },
            "DedicatedInternalFargateFour": {
                "command": None,
                "fargate": {"cpu": 256, "memory": 512},
                "http_interface": {
                    "alb_mode": "cluster",
                    "container_port": 80,
                    "health_check_path": "/",
                    "hostnames": [
                        "dedicated-internal-fargate-1.stagingsimpl.com",
                        "dedicated-internal-fargate-2.stagingsimpl.com",
                    ],
                    "internal": True,
                    "restrict_access_to": ["0.0.0.0/0"],
                },
                "logging": "awslogs",
                "memory_reservation": 100,
            },
            "DedicatedPublicECTwo": {
                "command": None,
                "http_interface": {
                    "alb_mode": "cluster",
                    "container_port": 80,
                    "health_check_path": "/",
                    "hostnames": [
                        "dedicated-public-ec2-1.stagingsimpl.com",
                        "dedicated-public-ec2-2.stagingsimpl.com",
                    ],
                    "internal": False,
                    "restrict_access_to": ["0.0.0.0/0"],
                },
                "logging": "awslogs",
                "memory_reservation": 100,
            },
            "DedicatedPublicFargateTwo": {
                "command": None,
                "fargate": {"cpu": 256, "memory": 512},
                "http_interface": {
                    "alb_mode": "cluster",
                    "container_port": 80,
                    "health_check_path": "/",
                    "hostnames": [
                        "dedicated-public-fargate-1.stagingsimpl.com",
                        "dedicated-public-fargate-2.stagingsimpl.com",
                    ],
                    "internal": False,
                    "restrict_access_to": ["0.0.0.0/0"],
                },
                "logging": None,
                "memory_reservation": 100,
            },
        },
    }


@pytest.fixture
def dummy_service_config_unmasked():
    return {
        "notifications_arn": SNS_TOPIC_ARN,
        "services": {
            "TestService": {
                "command": None,
                "http_interface": {
                    "alb_mode": "cluster",
                    "container_port": 80,
                    "health_check_path": "/",
                    "hostnames": ["test-service.example.com"],
                    "internal": True,
                    "restrict_access_to": ["0.0.0.0/0"],
                },
                "logging": None,
                "memory_reservation": 100,
                "spot_deployment": True,
                "depends_on": [
                    {
                        "container_name": "fluentbit-firelens-sidecar",
                        "condition": "START",
                    }
                ],
                "sidecars": [
                    {
                        "name": "fluentbit-firelens-sidecar",
                        "image_uri": "123456789012.dkr.ecr.ap-south-1.amazonaws.com/fluentbit-repo:latest",
                        "memory_reservation": 100,
                        "essential": True,
                    }
                ],
            },
        },
    }


@pytest.fixture(autouse=True)
def create_sns_topic(mock_aws):
    """
    Fixture to create an SNS topic.
    """
    sns_client = boto3.client("sns")
    sns_client.create_topic(Name=SNS_TOPIC_NAME)


@pytest.fixture
def environment_configuration(mock_aws, fast_sleep):
    """
    EnvironmentConfiguration object fixture.
    """
    env_config = EnvironmentConfiguration(ENVIRONMENT_NAME)
    return env_config


@pytest.fixture(autouse=True)
def environment_configuration_populated(
    environment_configuration, dummy_environment_config
):
    """
    Patch the environment configuration.
    """
    environment_configuration._set_config(dummy_environment_config)
    return environment_configuration


@pytest.fixture
def service_configuration(mock_aws, fast_sleep, environment_configuration):
    """
    Fixture to create a ServiceConfiguration object.
    """
    return ServiceConfiguration(service_name=SERVICE_NAME, environment=ENVIRONMENT_NAME)


@pytest.fixture
def service_configuration_populated(
    service_configuration, dummy_service_config, environment_configuration_populated
):
    service_configuration.set_config(dummy_service_config)
    return service_configuration


@pytest.fixture
def mock_dynamodb_table(monkeypatch, service_configuration):
    mock_table = MagicMock()
    monkeypatch.setattr(service_configuration, "table", mock_table)
    return mock_table


def test_edit_config_masks_configuration(
    service_configuration, monkeypatch, dummy_service_config_unmasked
):
    """
    Test that edit_config masks the configuration before sending it to the editor.
    """
    monkeypatch.setattr(
        service_configuration, "get_config", lambda x: dummy_service_config_unmasked
    )
    monkeypatch.setattr(
        service_configuration.config_utils,
        "fault_tolerant_edit_config",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(service_configuration, "set_config", MagicMock())

    service_configuration.edit_config()

    # Check if the configuration was masked
    masked_config = (
        service_configuration.config_utils.fault_tolerant_edit_config.call_args[1][
            "current_configuration"
        ]
    )
    assert "depends_on" not in masked_config["services"]["TestService"]
    assert "sidecars" not in masked_config["services"]["TestService"]


def test_edit_config_no_changes(
    service_configuration, monkeypatch, dummy_service_config_unmasked
):
    """
    Test that edit_config still invokes set_config even when no changes are made.
    """
    monkeypatch.setattr(
        service_configuration, "get_config", lambda x: dummy_service_config_unmasked
    )
    monkeypatch.setattr(
        service_configuration.config_utils,
        "fault_tolerant_edit_config",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(service_configuration, "set_config", MagicMock())

    service_configuration.edit_config()

    service_configuration.set_config.assert_called_once()


def test_edit_config_new_service(
    service_configuration, monkeypatch, dummy_service_config_unmasked
):
    """
    Test that edit_config uses the default configuration for a new service.
    """
    service_configuration.new_service = True
    monkeypatch.setattr(
        service_configuration,
        "_default_service_configuration",
        MagicMock(return_value=dummy_service_config_unmasked),
    )
    monkeypatch.setattr(
        service_configuration.config_utils,
        "fault_tolerant_edit_config",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(service_configuration, "set_config", MagicMock())

    service_configuration.edit_config()
    service_configuration.set_config.assert_called_once_with(
        dummy_service_config_unmasked
    )


def test_edit_config_prints_changes(
    service_configuration, service_configuration_populated, monkeypatch, capsys
):
    """
    Test that edit_config prints the changes when the configuration is modified.
    """
    # this returned config is not masked
    config = service_configuration.get_config(VERSION)
    modified_config = copy.deepcopy(config)

    # mask the keys that are not to be shown in the diff
    service_configuration._mask_config_keys(modified_config, ["depends_on", "sidecars"])
    modified_config["services"]["ClusterInternalECThree"]["memory_reservation"] = 200
    modified_config["services"]["ClusterInternalFargateThree"]["command"] = (
        "echo 'Hello, World!'"
    )
    del modified_config["services"]["ClusterInternalFargateThree"]["logging"]

    # as if any actor has made changes to the configuration
    monkeypatch.setattr(
        service_configuration.config_utils,
        "fault_tolerant_edit_config",
        MagicMock(return_value=modified_config),
    )
    monkeypatch.setattr(
        "cloudlift.config.service_configuration.confirm", lambda x: True
    )

    service_configuration.edit_config()

    capture = capsys.readouterr()

    print_json_changes(
        [
            (
                "change",
                "services.ClusterInternalECThree.memory_reservation",
                (100, 200),
            ),
            (
                "change",
                "services.ClusterInternalFargateThree.command",
                (None, "echo 'Hello, World!'"),
            ),
            (
                "remove",
                "services.ClusterInternalFargateThree",
                [("logging", "awsfirelens")],
            ),
        ]
    )
    manual_capture = capsys.readouterr()
    assert manual_capture.out in capture.out


def test_edit_config_prompts_for_confirmation(
    service_configuration, service_configuration_populated, monkeypatch
):
    """
    Test that edit_config prompts for confirmation when changes are made.
    """
    modified_config = copy.deepcopy(service_configuration.get_config(VERSION))

    modified_config["services"]["ClusterInternalECThree"]["memory_reservation"] = 200

    monkeypatch.setattr(
        service_configuration.config_utils,
        "fault_tolerant_edit_config",
        MagicMock(return_value=modified_config),
    )
    monkeypatch.setattr(service_configuration, "set_config", MagicMock())

    mock_confirm = MagicMock(return_value=True)
    monkeypatch.setattr("cloudlift.config.service_configuration.confirm", mock_confirm)

    service_configuration.edit_config()

    mock_confirm.assert_called_once_with("Do you want update the config?")


def test_edit_config_saves_on_confirmation(
    service_configuration, service_configuration_populated, monkeypatch
):
    """
    Test that edit_config saves the configuration when changes are confirmed.
    """
    service_config = service_configuration.get_config(VERSION)
    modified_config = copy.deepcopy(service_config)
    modified_config["services"]["ClusterInternalECThree"]["memory_reservation"] = 200
    monkeypatch.setattr(
        service_configuration.config_utils,
        "fault_tolerant_edit_config",
        MagicMock(return_value=modified_config),
    )
    monkeypatch.setattr(service_configuration, "set_config", MagicMock())
    monkeypatch.setattr(
        "cloudlift.config.service_configuration.confirm", lambda x: True
    )
    service_configuration.edit_config()
    service_configuration.set_config.assert_called_once_with(modified_config)


def test_edit_config_aborts_on_no_confirmation(
    service_configuration, service_configuration_populated, monkeypatch, capsys
):
    """
    Test that edit_config aborts when changes are not confirmed.
    """
    service_config = service_configuration.get_config(VERSION)
    modified_config = copy.deepcopy(service_config)
    modified_config["services"]["ClusterInternalECThree"]["memory_reservation"] = 200
    monkeypatch.setattr(
        service_configuration.config_utils,
        "fault_tolerant_edit_config",
        MagicMock(return_value=modified_config),
    )
    monkeypatch.setattr(service_configuration, "set_config", MagicMock())
    monkeypatch.setattr(
        "cloudlift.config.service_configuration.confirm", lambda x: False
    )

    service_configuration.edit_config()
    service_configuration.set_config.assert_not_called()
    captured = capsys.readouterr()
    assert "Changes aborted." in captured.out


def test_edit_config_unmasks_configuration(
    service_configuration, monkeypatch, dummy_service_config_unmasked
):
    """
    Test that edit_config unmasks the configuration before saving.
    """
    service_configuration.new_service = False
    monkeypatch.setattr(
        service_configuration, "get_config", lambda x: dummy_service_config_unmasked
    )
    modified_config = copy.deepcopy(dummy_service_config_unmasked)
    modified_config["services"]["TestService"]["memory_reservation"] = 200
    service_configuration._mask_config_keys(modified_config, ["depends_on", "sidecars"])
    monkeypatch.setattr(
        service_configuration.config_utils,
        "fault_tolerant_edit_config",
        MagicMock(return_value=modified_config),
    )
    set_config_mock = MagicMock()
    monkeypatch.setattr(service_configuration, "set_config", set_config_mock)
    monkeypatch.setattr(
        "cloudlift.config.service_configuration.confirm", lambda x: True
    )
    service_configuration.edit_config()

    saved_config = set_config_mock.call_args[0][0]
    assert "depends_on" in saved_config["services"]["TestService"]
    assert "sidecars" in saved_config["services"]["TestService"]


def test_get_config_existing_configuration(service_configuration, mock_dynamodb_table):
    """
    Test that get_config fetches the configuration from DynamoDB when it exists.
    """
    existing_config = {
        "configuration": {
            "services": {
                "TestService": {"memory_reservation": 256, "command": "echo Hello"}
            },
            "notifications_arn": "arn:aws:sns:us-east-1:123456789012:test-topic",
            "cloudlift_version": VERSION,
        }
    }
    mock_dynamodb_table.get_item.return_value = {"Item": existing_config}

    config = service_configuration.get_config(VERSION)

    assert config == existing_config["configuration"]
    assert not service_configuration.new_service


def test_get_config_no_configuration(service_configuration, mock_dynamodb_table):
    """
    Test that get_config returns the default configuration when no configuration exists.
    Also, test that the new_service flag is set to True.
    """
    mock_dynamodb_table.get_item.return_value = {}

    config = service_configuration.get_config(VERSION)

    assert config == service_configuration._default_service_configuration()
    assert service_configuration.new_service == True


def test_get_config_version_constraint(service_configuration, mock_dynamodb_table):
    """
    Test that get_config raises an exception when the existing configuration was created with a
    newer version.
    """
    older_version = "0.1.0"
    existing_config = {
        "configuration": {
            "services": {
                "TestService": {"memory_reservation": 256, "command": "echo Hello"}
            },
            "notifications_arn": "arn:aws:sns:us-east-1:123456789012:test-topic",
            "cloudlift_version": "1.0.0",  # Assuming current version is higher than this
        }
    }
    mock_dynamodb_table.get_item.return_value = {"Item": existing_config}

    with pytest.raises(UnrecoverableException) as excinfo:
        service_configuration.get_config(older_version)

    assert "Cloudlift Version 1.0.0 was used to create this service" in str(
        excinfo.value
    )


def test_get_config_client_error(service_configuration, mock_dynamodb_table):
    """
    Test that get_config raises an exception when a ClientError occurs while fetching the configuration.
    """
    mock_dynamodb_table.get_item.side_effect = ClientError(
        error_response={
            "Error": {"Code": "InternalServerError", "Message": "Internal server error"}
        },
        operation_name="GetItem",
    )

    with pytest.raises(UnrecoverableException) as excinfo:
        service_configuration.get_config(VERSION)

    assert "Unable to fetch service configuration from DynamoDB" in str(excinfo.value)


@pytest.fixture
def mock_validate_changes(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(ServiceConfiguration, "_validate_changes", mock)
    return mock


@pytest.fixture
def mock_check_sns_topic_exists(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(
        "cloudlift.config.service_configuration.check_sns_topic_exists", mock
    )
    return mock


def test_set_config_success(
    service_configuration,
    mock_validate_changes,
    mock_check_sns_topic_exists,
    monkeypatch,
    dummy_service_config,
):
    """
    Test that set_config successfully updates the configuration in DynamoDB.
    """
    mock_update_item = MagicMock(
        return_value={"Attributes": {"configuration": dummy_service_config}}
    )
    monkeypatch.setattr(service_configuration.table, "update_item", mock_update_item)

    result = service_configuration.set_config(dummy_service_config)

    mock_validate_changes.assert_called_once_with(
        {**dummy_service_config, "cloudlift_version": VERSION}
    )
    mock_check_sns_topic_exists.assert_called_once_with(
        dummy_service_config["notifications_arn"], ENVIRONMENT_NAME
    )
    mock_update_item.assert_called_once()
    assert result == {"Attributes": {"configuration": dummy_service_config}}


def test_set_config_validation_error(service_configuration, mock_validate_changes):
    """
    Test that set_config raises an UnrecoverableException when validation fails.
    """
    config = {"invalid": "config"}
    mock_validate_changes.side_effect = UnrecoverableException("Validation failed")

    with pytest.raises(UnrecoverableException, match="Validation failed"):
        service_configuration.set_config(config)


def test_set_config_sns_topic_not_found(
    service_configuration, mock_validate_changes, mock_check_sns_topic_exists
):
    """
    Test that set_config raises an UnrecoverableException when the SNS topic is not found.
    """
    config = {
        "notifications_arn": "arn:aws:sns:us-east-1:123456789012:non-existent-topic",
        "services": {},
    }
    mock_check_sns_topic_exists.side_effect = UnrecoverableException(
        "SNS topic not found"
    )

    with pytest.raises(UnrecoverableException, match="SNS topic not found"):
        service_configuration.set_config(config)


def test_set_config_dynamodb_error(
    service_configuration,
    mock_validate_changes,
    mock_check_sns_topic_exists,
    monkeypatch,
):
    """
    Test that set_config raises an UnrecoverableException when a DynamoDB error occurs.
    """
    config = {
        "notifications_arn": "arn:aws:sns:us-east-1:123456789012:test-topic",
        "services": {},
    }

    mock_update_item = MagicMock(
        side_effect=ClientError(
            error_response={
                "Error": {
                    "Code": "InternalServerError",
                    "Message": "Internal server error",
                }
            },
            operation_name="UpdateItem",
        )
    )
    monkeypatch.setattr(service_configuration.table, "update_item", mock_update_item)

    with pytest.raises(
        UnrecoverableException,
        match="Unable to store service configuration in DynamoDB",
    ):
        service_configuration.set_config(config)


def test_set_config_injects_cloudlift_version(
    service_configuration,
    mock_validate_changes,
    mock_check_sns_topic_exists,
    monkeypatch,
):
    """
    Test that set_config injects the cloudlift_version into the configuration.
    """
    config = {
        "notifications_arn": "arn:aws:sns:us-east-1:123456789012:test-topic",
        "services": {},
    }

    mock_update_item = MagicMock()
    monkeypatch.setattr(service_configuration.table, "update_item", mock_update_item)

    service_configuration.set_config(config)

    expected_config = {**config, "cloudlift_version": VERSION}
    mock_validate_changes.assert_called_once_with(expected_config)
    mock_update_item.assert_called_once()
    assert (
        mock_update_item.call_args[1]["ExpressionAttributeValues"][":configuration"]
        == expected_config
    )


def test_set_config_injects_fluentbit_sidecar(
    service_configuration,
    mock_validate_changes,
    mock_check_sns_topic_exists,
    monkeypatch,
    dummy_service_config,
):
    """
    Test that set_config invokes _inject_fluentbit_sidecar for all the services.

    _inject_fluentbit_sidecar method to be tested rigorously in separate test cases.
    """

    inject_fluentbit_sidecar_mock = MagicMock(
        wraps=service_configuration._inject_fluentbit_sidecar
    )
    monkeypatch.setattr(
        service_configuration,
        "_inject_fluentbit_sidecar",
        inject_fluentbit_sidecar_mock,
    )

    service_configuration.set_config(dummy_service_config)

    for service in dummy_service_config["services"]:
        inject_fluentbit_sidecar_mock.assert_any_call(
            dummy_service_config["services"][service]
        )


def test_set_config_injects_default_alb_mode(
    service_configuration, monkeypatch, dummy_service_config
):
    """
    Test that set_config invokes _inject_alb_mode for all the services.

    _inject_alb_mode method to be tested in separate test cases.
    """

    inject_alb_mode_mock = MagicMock(wraps=service_configuration._inject_alb_mode)
    monkeypatch.setattr(
        service_configuration,
        "_inject_alb_mode",
        inject_alb_mode_mock,
    )

    service_configuration.set_config(dummy_service_config)

    inject_alb_mode_mock.assert_any_call(dummy_service_config)


@pytest.mark.parametrize(
    "service_config, service_defaults, expected_result",
    [
        # Scenario 1: alb_mode not defined in service config, present in service_defaults
        (
            {"services": {"TestService": {"http_interface": {}}}},
            {"alb_mode": "cluster"},
            {"services": {"TestService": {"http_interface": {"alb_mode": "cluster"}}}},
        ),
        # Scenario 2: alb_mode not defined in service config or service_defaults
        (
            {"services": {"TestService": {"http_interface": {}}}},
            {},
            {
                "services": {
                    "TestService": {"http_interface": {"alb_mode": "dedicated"}}
                }
            },
        ),
        # Scenario 3: alb_mode defined in service config (should not be overridden)
        (
            {"services": {"TestService": {"http_interface": {"alb_mode": "cluster"}}}},
            {"alb_mode": "dedicated"},
            {"services": {"TestService": {"http_interface": {"alb_mode": "cluster"}}}},
        ),
        # Scenario 4: Multiple services, mixed configurations
        (
            {
                "services": {
                    "Service1": {"http_interface": {}},
                    "Service2": {"http_interface": {"alb_mode": "cluster"}},
                    "Service3": {"http_interface": {}},
                }
            },
            {"alb_mode": "dedicated"},
            {
                "services": {
                    "Service1": {"http_interface": {"alb_mode": "dedicated"}},
                    "Service2": {"http_interface": {"alb_mode": "cluster"}},
                    "Service3": {"http_interface": {"alb_mode": "dedicated"}},
                }
            },
        ),
        # Scenario 5: Service without http_interface
        (
            {"services": {"TestService": {}}},
            {"alb_mode": "cluster"},
            {"services": {"TestService": {}}},  # No alb_mode should be injected
        ),
    ],
)
def test_inject_alb_mode(
    service_configuration,
    service_config,
    service_defaults,
    expected_result,
    monkeypatch,
):
    """
    Test that _inject_alb_mode correctly injects the alb_mode based on service config and defaults.
    """
    monkeypatch.setattr(service_configuration, "service_defaults", service_defaults)

    result = service_configuration._inject_alb_mode(service_config)

    assert result == expected_result, f"Unexpected result: {result}"

    for service_name, service_data in result["services"].items():
        if "http_interface" in service_data:
            assert "alb_mode" in service_data["http_interface"], (
                f"alb_mode should be present in {service_name}"
            )
        else:
            assert "alb_mode" not in service_data, (
                f"alb_mode should not be present in {service_name} without http_interface"
            )


def test_inject_alb_mode_preserves_other_fields(service_configuration, monkeypatch):
    """
    Test that _inject_alb_mode preserves other fields in the configuration.
    """
    monkeypatch.setattr(
        service_configuration, "service_defaults", {"alb_mode": "cluster"}
    )

    config = {
        "services": {
            "TestService": {
                "http_interface": {"container_port": 8080},
                "memory_reservation": 256,
            }
        },
        "notifications_arn": "arn:aws:sns:us-east-1:123456789012:test-topic",
    }

    result = service_configuration._inject_alb_mode(config)

    assert result["services"]["TestService"]["http_interface"]["container_port"] == 8080
    assert result["services"]["TestService"]["memory_reservation"] == 256
    assert (
        result["notifications_arn"] == "arn:aws:sns:us-east-1:123456789012:test-topic"
    )
    assert result["services"]["TestService"]["http_interface"]["alb_mode"] == "cluster"


def test_update_cloudlift_version(service_configuration, monkeypatch):
    """
    Test that update_cloudlift_version correctly updates the cloudlift_version in the configuration.
    """
    # Mock the get_config method
    mock_config = {
        "services": {
            "TestService": {"memory_reservation": 256, "command": "echo Hello"}
        },
        "notifications_arn": "arn:aws:sns:us-east-1:123456789012:test-topic",
        "cloudlift_version": "1.0.0",  # Old version
    }
    mock_get_config = MagicMock(return_value=mock_config)
    monkeypatch.setattr(service_configuration, "get_config", mock_get_config)

    # Mock the set_config method
    mock_set_config = MagicMock()
    monkeypatch.setattr(service_configuration, "set_config", mock_set_config)

    # Call the method
    service_configuration.update_cloudlift_version()

    # Assertions
    mock_get_config.assert_called_once_with(VERSION)

    # set_config further injects cloudlift version, tested in
    # test_set_config_injects_cloudlift_version test case
    mock_set_config.assert_called_once_with(mock_config)


def test_validate_changes_invalid_configuration(
    service_configuration, monkeypatch, capsys
):
    """
    Test that _validate_changes raises an UnrecoverableException for an invalid configuration.
    """
    invalid_config_combos = [
        {
            "notifications_arn": "sns-arn",
            # scenario: service name is not in PascalCase
            "services": {"test-service": {}},
            "cloudlift_version": "1.0.0",
        },
        {
            "notifications_arn": "sns-arn",
            # scenario: service name starts with number (invalid)
            "services": {"1testService": {}},
            "cloudlift_version": "1.0.0",
        },
        {
            "notifications_arn": "sns-arn",
            "services": {
                "TestService": {
                    "memory_reservation": "invalid",  # Should be a number
                    "command": 123,  # Should be a string or null
                    "http_interface": {
                        "internal": "invalid",  # Should be a boolean
                        "restrict_access_to": "invalid",  # Should be an array
                        "container_port": "invalid",  # Should be a number
                        "health_check_path": 123,  # Should be a string
                        "alb_mode": "invalid",  # Should be "cluster" or "dedicated"
                        "hostnames": "invalid",  # Should be an array
                    },
                }
            },
            "cloudlift_version": "1.0.0",
        },
    ]

    for invalid_config in invalid_config_combos:
        with pytest.raises(UnrecoverableException) as excinfo:
            service_configuration._validate_changes(invalid_config)


@pytest.mark.parametrize(
    "service_defaults, expected_result",
    [
        # Scenario 1: environment_service_defaults is None
        (
            None,
            {
                "services.TestService.http_interface.alb_mode": "dedicated",
            },
        ),
        # Scenario 2: environment_service_defaults is empty
        (
            {},
            {
                "services.TestService.http_interface.alb_mode": "dedicated",
            },
        ),
        # Scenario 3: environment_service_defaults has alb_mode defined
        (
            {"alb_mode": "cluster"},
            {
                "services.TestService.http_interface.alb_mode": "cluster",
            },
        ),
        # Scenario 4: environment_service_defaults has alb_mode defined as "dedicated"
        (
            {"alb_mode": "dedicated"},
            {
                "services.TestService.http_interface.alb_mode": "dedicated",
            },
        ),
    ],
)
def test_default_service_configuration(
    service_defaults, expected_result, dummy_environment_config
):
    """
    Test that _default_service_configuration returns the expected default configuration.
    """
    environment_configuration = EnvironmentConfiguration(ENVIRONMENT_NAME)
    if service_defaults is None:
        del dummy_environment_config[ENVIRONMENT_NAME]["service_defaults"]
    else:
        dummy_environment_config[ENVIRONMENT_NAME]["service_defaults"] = (
            service_defaults
        )
    environment_configuration._set_config(dummy_environment_config)
    service_configuration = ServiceConfiguration(
        service_name=SERVICE_NAME, environment=ENVIRONMENT_NAME
    )
    service_configuration.environment_configuration = environment_configuration

    default_config = service_configuration._default_service_configuration()
    default_config_flat = flatten_dict(default_config)
    for key, value in expected_result.items():
        assert key in default_config_flat
        assert default_config_flat[key] == value
    assert "notifications_arn" in default_config
    assert default_config["notifications_arn"] is None
    assert "services" in default_config
    assert "TestService" in default_config["services"]
    assert "http_interface" in default_config["services"]["TestService"]

    test_service = default_config["services"]["TestService"]

    assert test_service["http_interface"]["internal"] is True
    assert test_service["http_interface"]["restrict_access_to"] == ["0.0.0.0/0"]
    assert test_service["http_interface"]["container_port"] == 80
    assert test_service["http_interface"]["health_check_path"] == "/elb-check"
    assert test_service["http_interface"]["hostnames"] == []
    assert test_service["memory_reservation"] == 250
    assert test_service["command"] is None
    assert test_service["spot_deployment"] is False


def test_mask_config_keys(service_configuration, dummy_service_config_unmasked):
    """
    Test that _mask_config_keys correctly masks specified keys in the configuration.
    """
    keys_to_mask = ["depends_on", "sidecars"]

    masked_config, masked_keys = service_configuration._mask_config_keys(
        copy.deepcopy(dummy_service_config_unmasked), keys_to_mask
    )

    # Check if keys are masked in the configuration
    assert "depends_on" not in masked_config["services"]["TestService"]
    assert "sidecars" not in masked_config["services"]["TestService"]

    # Check if masked keys are stored correctly
    assert service_configuration.masked_config_keys["TestService"]["depends_on"] == [
        {
            "container_name": "fluentbit-firelens-sidecar",
            "condition": "START",
        }
    ]
    assert service_configuration.masked_config_keys["TestService"]["sidecars"] == [
        {
            "name": "fluentbit-firelens-sidecar",
            "image_uri": "123456789012.dkr.ecr.ap-south-1.amazonaws.com/fluentbit-repo:latest",
            "memory_reservation": 100,
            "essential": True,
        }
    ]

    # Check if non-masked keys remain intact
    assert masked_config["services"]["TestService"]["memory_reservation"] == 100
    assert masked_config["services"]["TestService"]["command"] is None


def test_mask_config_keys_no_keys_to_mask(
    service_configuration, dummy_service_config_unmasked
):
    """
    Test that _mask_config_keys returns the original configuration when no keys are specified to
    mask.
    """
    keys_to_mask = []

    masked_config, masked_keys = service_configuration._mask_config_keys(
        copy.deepcopy(dummy_service_config_unmasked), keys_to_mask
    )

    assert masked_config == dummy_service_config_unmasked
    assert service_configuration.masked_config_keys == {"TestService": {}}


def test_unmask_config_keys(service_configuration, dummy_service_config_unmasked):
    """
    Test that _unmask_config_keys correctly unmasks previously masked keys in the configuration.
    """
    keys_to_mask = ["depends_on", "sidecars"]

    # First, mask the keys
    masked_config, _ = service_configuration._mask_config_keys(
        copy.deepcopy(dummy_service_config_unmasked), keys_to_mask
    )

    # Now, unmask the keys
    unmasked_config = service_configuration._unmask_config_keys(masked_config)

    # Check if keys are unmasked correctly
    assert "depends_on" in unmasked_config["services"]["TestService"]
    assert "sidecars" in unmasked_config["services"]["TestService"]

    # Check if unmasked values are correct
    assert (
        unmasked_config["services"]["TestService"]["depends_on"]
        == dummy_service_config_unmasked["services"]["TestService"]["depends_on"]
    )
    assert (
        unmasked_config["services"]["TestService"]["sidecars"]
        == dummy_service_config_unmasked["services"]["TestService"]["sidecars"]
    )


def test_unmask_config_keys_no_masked_keys(
    service_configuration, dummy_service_config_unmasked
):
    """
    Test that _unmask_config_keys returns the original configuration when no keys were previously
    masked.
    """
    unmasked_config = service_configuration._unmask_config_keys(
        copy.deepcopy(dummy_service_config_unmasked)
    )

    assert unmasked_config == dummy_service_config_unmasked


def test_mask_unmask_config_keys_idempotence(
    service_configuration, dummy_service_config_unmasked
):
    """
    Test that masking and then unmasking config keys results in the original configuration.
    """
    keys_to_mask = ["depends_on", "sidecars"]

    masked_config, _ = service_configuration._mask_config_keys(
        copy.deepcopy(dummy_service_config_unmasked), keys_to_mask
    )
    unmasked_config = service_configuration._unmask_config_keys(masked_config)

    assert unmasked_config == dummy_service_config_unmasked


@pytest.fixture
def mock_fluenbit_uri_prompt(monkeypatch):
    mock = MagicMock(return_value="mock-fluentbit-image:latest")
    monkeypatch.setattr("cloudlift.config.service_configuration.prompt", mock)
    return mock


def test_inject_fluentbit_sidecar_awsfirelens(
    service_configuration, dummy_environment_config
):
    """
    Test injection of fluentbit sidecar when logging is set to 'awsfirelens'.
    """
    service_config = {"logging": "awsfirelens", "memory_reservation": 100}
    result = service_configuration._inject_fluentbit_sidecar(service_config)

    assert FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME in [
        sidecar["name"] for sidecar in result["sidecars"]
    ]
    assert (
        result["depends_on"][0]["container_name"]
        == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
    )
    assert result["depends_on"][0]["condition"] == "START"


def test_inject_fluentbit_sidecar_awslogs(service_configuration):
    """
    Test that fluentbit sidecar is not injected when logging is set to 'awslogs'.
    """
    service_config = {"logging": "awslogs", "memory_reservation": 100}
    result = service_configuration._inject_fluentbit_sidecar(service_config)

    assert "sidecars" not in result
    assert "depends_on" not in result


def test_inject_fluentbit_sidecar_none(service_configuration):
    """
    Test that fluentbit sidecar is not injected when logging is set to None.
    """
    service_config = {"logging": None, "memory_reservation": 100}
    result = service_configuration._inject_fluentbit_sidecar(service_config)

    assert "sidecars" not in result
    assert "depends_on" not in result


def test_inject_fluentbit_sidecar_already_present(service_configuration):
    """
    Test that no additional fluentbit sidecar is injected if it's already present.
    """
    service_config = {
        "logging": "awsfirelens",
        "memory_reservation": 100,
        "sidecars": [
            {
                "name": FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME,
                "image_uri": "existing-fluentbit-image:latest",
                "memory_reservation": 50,
                "essential": True,
            }
        ],
    }
    result = service_configuration._inject_fluentbit_sidecar(service_config)

    assert (
        len(
            [
                sidecar
                for sidecar in result["sidecars"]
                if sidecar["name"] == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
            ]
        )
        == 1
    )
    assert result["sidecars"][0]["image_uri"] == "existing-fluentbit-image:latest"


def test_inject_fluentbit_sidecar_remove_when_logging_changed(service_configuration):
    """
    Test that fluentbit sidecar is removed when logging is changed from 'awsfirelens' to something else.
    """
    service_config = {
        "logging": "awslogs",
        "memory_reservation": 100,
        "sidecars": [
            {
                "name": FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME,
                "image_uri": "fluentbit-image:latest",
                "memory_reservation": 50,
                "essential": True,
            }
        ],
        "depends_on": [
            {
                "container_name": FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME,
                "condition": "START",
            }
        ],
    }
    result = service_configuration._inject_fluentbit_sidecar(service_config)

    assert "sidecars" not in result
    assert "depends_on" not in result


def test_inject_fluentbit_sidecar_use_environment_config(
    service_configuration, dummy_environment_config
):
    """
    Test that fluentbit sidecar uses configuration from environment when available.
    """
    service_config = {"logging": "awsfirelens", "memory_reservation": 100}
    result = service_configuration._inject_fluentbit_sidecar(service_config)

    assert (
        result["sidecars"][0]["image_uri"]
        == "123456789012.dkr.ecr.ap-south-1.amazonaws.com/fluentbit-repo:latest"
    )
    assert result["sidecars"][0]["env"]["kinesis_role_arn"] == ""


def test_inject_fluentbit_sidecar_prompt_for_image(
    dummy_environment_config,
    mock_fluenbit_uri_prompt,
    environment_configuration,
):
    """
    Test that user is prompted for fluentbit image when not available in environment config.
    """
    service_config = {"logging": "awsfirelens", "memory_reservation": 100}
    # Remove fluentbit config from environment config
    del dummy_environment_config[ENVIRONMENT_NAME]["service_defaults"][
        "fluentbit_config"
    ]
    environment_configuration._set_config(dummy_environment_config)
    service_configuration = ServiceConfiguration(
        service_name=SERVICE_NAME, environment=ENVIRONMENT_NAME
    )
    result = service_configuration._inject_fluentbit_sidecar(service_config)
    mock_fluenbit_uri_prompt.assert_called_once()
    assert result["sidecars"][0]["image_uri"] == "mock-fluentbit-image:latest"


def test_inject_fluentbit_sidecar_preserve_other_sidecars(service_configuration):
    """
    Test that other sidecars are preserved when injecting fluentbit sidecar.
    """
    service_config = {
        "logging": "awsfirelens",
        "memory_reservation": 100,
        "sidecars": [
            {
                "name": "other-sidecar",
                "image_uri": "other-image:latest",
                "memory_reservation": 50,
                "essential": True,
            }
        ],
    }
    result = service_configuration._inject_fluentbit_sidecar(service_config)

    assert len(result["sidecars"]) == 2
    assert any(sidecar["name"] == "other-sidecar" for sidecar in result["sidecars"])
    assert any(
        sidecar["name"] == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
        for sidecar in result["sidecars"]
    )


def test_inject_fluentbit_sidecar_environment_variables(
    service_configuration, dummy_environment_config, monkeypatch
):
    """
    Test that additional environment variables from the environment config are injected into the fluentbit sidecar.
    """
    service_config = {"logging": "awsfirelens", "memory_reservation": 100}

    # Add additional environment variables to the environment config
    additional_env_vars = {"TEST_VAR1": "test_value1", "TEST_VAR2": "test_value2"}
    service_configuration.service_defaults["fluentbit_config"]["env"] = (
        additional_env_vars
    )

    result = service_configuration._inject_fluentbit_sidecar(service_config)

    fluentbit_sidecar = next(
        sidecar
        for sidecar in result["sidecars"]
        if sidecar["name"] == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
    )

    assert "env" in fluentbit_sidecar
    assert fluentbit_sidecar["env"]["TEST_VAR1"] == "test_value1"
    assert fluentbit_sidecar["env"]["TEST_VAR2"] == "test_value2"
    assert (
        fluentbit_sidecar["env"]["delivery_stream"]
        == f"{service_configuration.environment}-{service_configuration.service_name}"
    )
    assert (
        fluentbit_sidecar["env"]["CL_ENVIRONMENT"] == service_configuration.environment
    )
    assert fluentbit_sidecar["env"]["CL_SERVICE"] == service_configuration.service_name


def test_inject_fluentbit_sidecar_default_env_vars(
    service_configuration, dummy_environment_config
):
    """
    Test that default environment variables are set when not provided in the environment config.
    """
    service_config = {"logging": "awsfirelens", "memory_reservation": 100}

    result = service_configuration._inject_fluentbit_sidecar(service_config)

    fluentbit_sidecar = next(
        sidecar
        for sidecar in result["sidecars"]
        if sidecar["name"] == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
    )

    assert "env" in fluentbit_sidecar
    assert (
        fluentbit_sidecar["env"]["delivery_stream"]
        == f"{service_configuration.environment}-{service_configuration.service_name}"
    )
    assert (
        fluentbit_sidecar["env"]["CL_ENVIRONMENT"] == service_configuration.environment
    )
    assert fluentbit_sidecar["env"]["CL_SERVICE"] == service_configuration.service_name
    assert "kinesis_role_arn" in fluentbit_sidecar["env"]


def test_inject_fluent_bit_sidecar_properties(
    service_configuration, dummy_environment_config
):
    """
    Test that the properties of the fluent bit sidecar are injected correctly.
    """
    service_config = {
        "logging": "awsfirelens",
        "memory_reservation": 100,
        "sidecars": [
            {
                "name": "other-sidecar",
                "image_uri": "other-image:latest",
                "memory_reservation": 50,
                "essential": True,
            }
        ],
    }
    result = service_configuration._inject_fluentbit_sidecar(service_config)

    assert len(result["sidecars"]) == 2
    assert any(sidecar["name"] == "other-sidecar" for sidecar in result["sidecars"])
    assert any(
        sidecar["name"] == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
        for sidecar in result["sidecars"]
    )
    fluentbit_sidecar = next(
        sidecar
        for sidecar in result["sidecars"]
        if sidecar["name"] == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
    )
    fluentbit_env_service_defaults = dummy_environment_config[ENVIRONMENT_NAME][
        "service_defaults"
    ]["fluentbit_config"]

    assert fluentbit_sidecar["memory_reservation"] == 100
    assert fluentbit_sidecar["essential"] == True
    assert (
        result["sidecars"][1]["image_uri"]
        == fluentbit_env_service_defaults["image_uri"]
    )
    assert (
        result["sidecars"][1]["env"]["kinesis_role_arn"]
        == fluentbit_env_service_defaults["env"]["kinesis_role_arn"]
    )
    assert fluentbit_sidecar["health_check"] == {
        "command": [
            "CMD-SHELL",
            "curl -f -s http://localhost:2020/api/v1/health || exit 1",
        ],
        "interval": 5,
        "timeout": 2,
        "retries": 3,
    }


@pytest.mark.parametrize(
    "cpu_reservation,is_valid",
    [
        # Valid values
        (CPU_MIN_VALUE, True),
        (CPU_MID_VALUE, True),
        (CPU_MAX_VALUE, True),
        # Invalid values
        (CPU_MIN_VALUE - 1, False),
        (False, False),
        (0, False),
        (CPU_MAX_VALUE + 1, False),
        ("1024", False),
        # None
        (None, True),
    ],
)
def test_validate_changes_cpu_reservation_values(
    service_configuration, cpu_reservation, is_valid
):
    """
    Test that _validate_changes correctly validates the cpu_reservation settings.
    """
    config = {
        "notifications_arn": "sns-arn",
        "services": {
            "TestService": {
                "memory_reservation": 100,
                "command": None,
            }
        },
        "cloudlift_version": "1.0.0",
    }

    # Add cpu_reservation to the config only if it's not None
    if cpu_reservation is not None:
        config["services"]["TestService"]["cpu_reservation"] = cpu_reservation

    if is_valid:
        # Should not raise an exception
        service_configuration._validate_changes(config)
    else:
        with pytest.raises(UnrecoverableException):
            service_configuration._validate_changes(config)


def test_validate_changes_cpu_configs_optional(service_configuration):
    """
    Test that the cpu_reservation field is optional and does not raise an exception
    """
    config = {
        "notifications_arn": "sns-arn",
        "services": {
            "TestService": {
                "memory_reservation": 100,
                "command": None,
                # No cpu_reservation is specified
            }
        },
        "cloudlift_version": "1.0.0",
    }

    # Should not raise an exception as cpu_reservation is optional
    service_configuration._validate_changes(config)


@pytest.mark.parametrize(
    "service_name, should_be_valid",
    [
        # Valid service names (should not raise exception)
        ("TestService", True),  # PascalCase
        ("testservice", True),  # lowercase
        ("Service1", True),  # letters + numbers
        ("Test123", True),  # letters + numbers
        ("testService080", True),  # complex with numbers
        ("Unity", True),  # single word
        ("Kafdrop2", True),  # letters + number at end
        ("A", True),  # single letter
        ("testService123", True),  # complex with numbers
        ("MerchantDashboardD2C", True),  # mixed case with numbers
        # Invalid service names (should raise exception)
        ("1test-service", False),  # starts with number
        ("-invalid", False),  # starts with hyphen
        ("service_underscore", False),  # contains underscore
        ("service.", False),  # contains period
        ("service name", False),  # contains space
        (
            "test-",
            False,
        ),  # ends with hyphen (invalid)
        ("", False),  # empty string
    ],
)
def test_service_name_validation(service_configuration, service_name, should_be_valid):
    """
    Test service name validation with regex pattern that allows letters and numbers only.
    Service names must start with a letter and cannot contain hyphens or special characters.
    """
    config = {
        "notifications_arn": "sns-arn",
        "services": {
            service_name: {
                "memory_reservation": 100,
                "command": None,
            }
        },
        "cloudlift_version": "1.0.0",
    }

    if should_be_valid:
        # Should not raise an exception
        service_configuration._validate_changes(config)
    else:
        # Should raise UnrecoverableException
        with pytest.raises(UnrecoverableException):
            service_configuration._validate_changes(config)
