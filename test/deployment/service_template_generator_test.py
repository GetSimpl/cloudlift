import datetime
import os
from decimal import Decimal
from unittest import TestCase

from cfn_flip import to_json
from mock import patch, MagicMock

from cloudlift.config import ServiceConfiguration
from cloudlift.deployment.service_template_generator import ServiceTemplateGenerator
from cloudlift.version import VERSION

def mocked_service_config():
    return {
        "cloudlift_version": VERSION,
        "notifications_arn": "some",
        "services": {
            "Dummy": {
                "memory_reservation": Decimal(1000),
                "command": None,
                "http_interface": {
                    "internal": False,
                    "container_port": Decimal(7003),
                    "restrict_access_to": ["0.0.0.0/0"],
                    "health_check_path": "/elb-check"
                },
                "deployment": {
                    "maximum_percent": Decimal(150)
                }
            },
            "DummyRunSidekiqsh": {
                "memory_reservation": Decimal(1000),
                "command": "./run-sidekiq.sh",
                "deployment": {
                    "maximum_percent": Decimal(150)  # The configuration is read as decimal always
                }
            }
        }
    }


def mocked_fargate_service_config():
    return {
        "cloudlift_version": VERSION,
        "notifications_arn": "some",
        "services": {
            "DummyFargateRunSidekiqsh": {
                "command": None,
                "fargate": {
                    "cpu": 256,
                    "memory": 512
                },
                "memory_reservation": 512
            },
            "DummyFargateService": {
                "command": None,
                "fargate": {
                    "cpu": 256,
                    "memory": 512
                },
                "http_interface": {
                    "container_port": 80,
                    "internal": False,
                    "restrict_access_to": [
                        "0.0.0.0/0"
                    ],
                    "health_check_path": "/elb-check"
                },
                "memory_reservation": 512
            }
        }
    }


class TestServiceTemplateGenerator(TestCase):

    @patch('cloudlift.config.service_configuration.get_resource_for')
    @patch('cloudlift.deployment.service_template_generator.ServiceInformationFetcher')
    def test_initialization(self, mockServiceInformationFetcher, mock_get_resource_for):
        service_config = ServiceConfiguration("test-service", "staging")

        generator = ServiceTemplateGenerator(service_config, None)

        mock_get_resource_for.assert_called_with('dynamodb', 'staging')
        mockServiceInformationFetcher.assert_called_with("test-service", "staging")
        assert generator.env == 'staging'
        assert generator.application_name == 'test-service'
        assert generator.environment_stack is None

    @patch('cloudlift.deployment.service_template_generator.ServiceInformationFetcher')
    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    def test_generate_service(self, mock_region_service, mock_get_account_id, mock_build_config, mockServiceInformationFetcher):
        environment = 'staging'
        application_name = 'dummy'
        mock_service_info_inst = mockServiceInformationFetcher.return_value
        mock_service_info_inst.get_current_version.return_value = "1.1.1"
        mock_service_info_inst.fetch_current_desired_count.return_value = {"Dummy": 100, "DummyRunSidekiqsh": 199}
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name, environment=environment)
        mock_service_configuration.get_config.return_value = mocked_service_config()
        mock_build_config.return_value = [("PORT", "80")]
        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack())
        template_generator.env_sample_file_path = './test/templates/test_env.sample'
        generated_template = template_generator.generate_service()

        template_file_path = os.path.join(os.path.dirname(__file__), '../templates/expected_service_template.yml')
        with(open(template_file_path)) as expected_template_file:
            assert to_json(''.join(expected_template_file.readlines())) == to_json(generated_template)

    @patch('cloudlift.deployment.service_template_generator.ServiceInformationFetcher')
    @patch('cloudlift.deployment.service_template_generator.build_config')
    @patch('cloudlift.deployment.service_template_generator.get_account_id')
    @patch('cloudlift.deployment.template_generator.region_service')
    @patch('cloudlift.deployment.service_template_generator.boto3')
    def test_generate_fargate_service(self, mock_boto, mock_region_service, mock_get_account_id, mock_build_config, mockServiceInformationFetcher):
        environment = 'staging'
        application_name = 'dummyFargate'
        mock_service_info_inst = mockServiceInformationFetcher.return_value
        mock_service_info_inst.get_current_version.return_value = "1.1.1"
        mock_service_info_inst.fetch_current_desired_count.return_value = {"DummyFargateService": 45, "DummyFargateRunSidekiqsh": 51}
        mock_service_configuration = MagicMock(spec=ServiceConfiguration, service_name=application_name, environment=environment)
        mock_service_configuration.get_config.return_value = mocked_fargate_service_config()
        mock_build_config.return_value = [("PORT", "80")]
        mock_get_account_id.return_value = "12537612"
        mock_region_service.get_region_for_environment.return_value = "us-west-2"
        mock_iam_role = MagicMock(arn="arn:aws:iam::12537612:role/DummyExecutionRole")
        mock_boto.resource.return_value = MagicMock()
        mock_boto.resource.return_value.Role.return_value = mock_iam_role

        template_generator = ServiceTemplateGenerator(mock_service_configuration, self._get_env_stack())
        template_generator.env_sample_file_path = './test/templates/test_env.sample'
        generated_template = template_generator.generate_service()

        template_file_path = os.path.join(os.path.dirname(__file__), '../templates/expected_fargate_service_template.yml')
        with(open(template_file_path)) as expected_template_file:
            assert to_json(''.join(expected_template_file.readlines())) == to_json(generated_template)

    @staticmethod
    def _get_env_stack():
        return {u'StackId': 'arn:aws:cloudformation:ap-south-1:725827686899:stack/cluster-staging/65410f80-d21c-11e8-913a-503a56826a2a', u'LastUpdatedTime': datetime.datetime(2018, 11, 9, 5, 22, 30, 691000), u'Parameters': [{u'ParameterValue': 'staging-cluster-v3', u'ParameterKey': 'KeyPair'}, {u'ParameterValue': '1', u'ParameterKey': 'ClusterSize'}, {u'ParameterValue': 'arn:aws:sns:ap-south-1:725827686899:non-prod-mumbai', u'ParameterKey': 'NotificationSnsArn'}, {u'ParameterValue': 'staging', u'ParameterKey': 'Environment'}, {u'ParameterValue': 'm5.xlarge', u'ParameterKey': 'InstanceType'}, {u'ParameterValue': '50', u'ParameterKey': 'MaxSize'}], u'Tags': [], u'Outputs': [{u'Description': 'VPC in which environment is setup', u'OutputKey': 'VPC', u'OutputValue': 'vpc-00f07c5a6b6c9abdb'}, {u'Description': 'Options used with cloudlift when building this cluster', u'OutputKey': 'CloudliftOptions', u'OutputValue': '{"min_instances": 1, "key_name": "staging-cluster-v3", "max_instances": 50, "instance_type": "m5.xlarge", "cloudlift_version": "0.9.4", "env": "staging"}'}, {u'Description': 'Maximum instances in cluster', u'OutputKey': 'MaxInstances', u'OutputValue': '50'}, {u'Description': 'Security group ID for ALB', u'OutputKey': 'SecurityGroupAlb', u'OutputValue': 'sg-095dbeb511019cfd8'}, {u'Description': 'Key Pair name for accessing the instances', u'OutputKey': 'KeyName', u'OutputValue': 'staging-cluster-v3'}, {
            u'Description': 'ID of the 1st subnet', u'OutputKey': 'PrivateSubnet1', u'OutputValue': 'subnet-09b6cd23af94861cc'}, {u'Description': 'ID of the 2nd subnet', u'OutputKey': 'PrivateSubnet2', u'OutputValue': 'subnet-0657bc2faa99ce5f7'}, {u'Description': 'Minimum instances in cluster', u'OutputKey': 'MinInstances', u'OutputValue': '1'}, {u'Description': 'ID of the 2nd subnet', u'OutputKey': 'PublicSubnet2', u'OutputValue': 'subnet-096377a44ccb73aca'}, {u'Description': 'EC2 instance type', u'OutputKey': 'InstanceType', u'OutputValue': 'm5.xlarge'}, {u'Description': 'ID of the 1st subnet', u'OutputKey': 'PublicSubnet1', u'OutputValue': 'subnet-0aeae8fe5e13a7ff7'}, {u'Description': 'The name of the stack', u'OutputKey': 'StackName', u'OutputValue': 'cluster-staging'}, {u'Description': 'The unique ID of the stack. To be supplied to circle CI environment variables to validate during deployment.', u'OutputKey': 'StackId', u'OutputValue': 'arn:aws:cloudformation:ap-south-1:725827686899:stack/cluster-staging/65410f80-d21c-11e8-913a-503a56826a2a'}], u'CreationTime': datetime.datetime(2018, 10, 17, 14, 53, 23, 469000), u'Capabilities': ['CAPABILITY_NAMED_IAM'], u'StackName': 'cluster-staging', u'NotificationARNs': [], u'StackStatus': 'UPDATE_COMPLETE', u'DisableRollback': True, u'ChangeSetId': 'arn:aws:cloudformation:ap-south-1:725827686899:changeSet/cg901a2f5dbf984b9e9807a21da1ac7d12/7588cd05-1e2d-4dd6-85ab-12b921baa814', u'RollbackConfiguration': {}}
