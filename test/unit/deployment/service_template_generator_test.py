import os
from unittest.mock import Mock, patch

import boto3
import pytest
from moto import mock_aws as moto_mock_aws
from troposphere.ecs import LogConfiguration

from cloudlift.deployment import ServiceTemplateGenerator


@pytest.fixture
def mock_aws(test_aws_credentials):
    """
    Mock all AWS interactions
    """
    with moto_mock_aws():
        # Create the IAM role that the test expects
        iam = boto3.client("iam")
        try:
            trust_policy = """{
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                        "Action": "sts:AssumeRole"
                    }
                ]
            }"""
            iam.create_role(
                RoleName="ecsTaskExecutionRole", AssumeRolePolicyDocument=trust_policy
            )
        except Exception as e:
            print(f"Error creating role: {e}")
        yield


class ServiceConfig:
    def __init__(self):
        self.environment = "test-environment"
        self.notification_arn = "arn:aws:sns:us-east-1:123456789012:my-topic"
        self.notifications_arn = "arn:aws:sns:us-east-1:123456789012:my-topic"
        self.service_name = "testservice"
        self.services = {
            self.service_name: {
                "command": None,
                "memory_reservation": 512,
            }
        }
        self.team_name = "test-team"

    def get_config(self, cloudlift_version):
        return {
            "environment": self.environment,
            "notification_arn": self.notification_arn,
            "services": self.services,
        }


class MockServiceTemplateGenerator(ServiceTemplateGenerator):
    @property
    def notifications_arn(self):
        return "arn:aws:sns:us-east-1:123456789012:my-topic"

    @property
    def ecr_image_uri(self):
        return "123456789012.dkr.ecr.us-east-1.amazonaws.com/test-service:latest"

    def __init__(self, service_configuration, environment_stack):
        super().__init__(service_configuration, environment_stack)
        self.application_name = "test-service"
        self.env = "test-environment"
        self.desired_counts = {}
        self.notification_sns_arn = "arn:aws:sns:us-east-1:123456789012:my-topic"

    def _gen_log_config(self, service_name, config):
        return LogConfiguration(
            LogDriver="awslogs",
            Options={
                "awslogs-stream-prefix": service_name,
                "awslogs-group": "-".join([self.env, "logs"]),
                "awslogs-region": "ap-south-1",
            },
        )


@pytest.fixture
def service_config():
    return ServiceConfig()


@pytest.fixture
def environment_stack():
    return {"Outputs": {}}


@pytest.fixture
def mocked_dependencies():
    """Fixture to set up all the necessary mocks for the ServiceTemplateGenerator"""
    with (
        patch(
            "cloudlift.deployment.service_template_generator.ServiceInformationFetcher"
        ) as mock_service_info_fetcher,
        patch(
            "cloudlift.deployment.service_template_generator.get_client_for"
        ) as mock_get_client,
        patch(
            "cloudlift.deployment.service_template_generator.EnvironmentConfiguration"
        ) as mock_env_config,
        patch(
            "cloudlift.deployment.service_template_generator.build_config"
        ) as mock_build_config,
        patch(
            "cloudlift.deployment.service_template_generator.LogConfiguration"
        ) as mock_log_config,
    ):
        # Set up mocks
        mock_build_config.return_value = {"KEY": "VALUE"}.items()

        mock_log_config.return_value = Mock()

        mock_instance = mock_service_info_fetcher.return_value
        mock_instance.get_current_version.return_value = "1.0.0"

        mock_client = Mock()
        mock_get_client.return_value = mock_client

        mock_env_instance = mock_env_config.return_value
        mock_env_instance.get_config.return_value = {
            "test-environment": {"service_defaults": {}}
        }

        yield


@pytest.fixture
def service_template_generator(service_config, environment_stack, mocked_dependencies):
    """Fixture to create a properly configured ServiceTemplateGenerator instance"""
    generator = MockServiceTemplateGenerator(service_config, environment_stack)
    return generator


MULTIPLIER = 1.25


class TestCpuConfiguration:
    # parametrize the test with different CPU configurations
    @pytest.mark.parametrize(
        "cpu_reservation, expected_container_cpu, expected_task_cpu",
        [
            # Normal values
            (256, 256, int(256 * MULTIPLIER)),
            (128, 128, int(128 * MULTIPLIER)),
            # None values
            (None, 0, None),
        ],
    )
    def test_cpu_configuration(
        self,
        service_template_generator,
        service_config,
        mock_aws,
        cpu_reservation,
        expected_container_cpu,
        expected_task_cpu,
    ):
        """
        Test that the CPU configuration is set correctly in the CloudFormation template.
        This test checks the following scenarios:
        1. When cpu_reservation is set to a normal value, the container CPU is set to that value,
           and the task CPU is set to the value multiplied by a constant.
        2. When cpu_reservation is None, the container CPU is set to 0, and the task CPU is None.
        """
        # Set CPU values in service config
        service_name = "testservice"
        service_config.services[service_name]["cpu_reservation"] = cpu_reservation

        # Create the service template generator
        config = service_config.services[service_name]

        # Create the service template generator
        service_template_generator._add_service(service_name, config)

        resources = service_template_generator.template.to_dict().get("Resources", {})
        task_definition = resources.get(f"{service_name}TaskDefinition")
        container_definitions = task_definition.get("Properties", {}).get(
            "ContainerDefinitions", {}
        )

        container_definition = None
        for container in container_definitions:
            if container.get("Name") == f"{service_name}Container":
                container_definition = container
                break

        assert container_definition is not None
        assert task_definition is not None

        actual_cpu_container = container_definition.get("Cpu", None)
        assert actual_cpu_container == expected_container_cpu

        if cpu_reservation:
            actual_cpu_task = int(
                float(task_definition.get("Properties", {}).get("Cpu"))
            )
            assert actual_cpu_task == expected_task_cpu
