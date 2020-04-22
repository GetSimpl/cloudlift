import datetime

from cfn_flip import to_json
from mock import patch

from cloudlift.config import ParameterStore
from cloudlift.config import ServiceConfiguration
from cloudlift.deployment.service_information_fetcher import ServiceInformationFetcher
from cloudlift.deployment.service_template_generator import ServiceTemplateGenerator
from cloudlift.version import VERSION


def mocked_service_config(cls, *args, **kwargs):
    return {
        "cloudlift_version": VERSION,
        "services": {
            "Dummy": {
                "memory_reservation": 1000,
                "command": None,
                "http_interface": {
                    "internal": False,
                    "container_port": 7003,
                    "restrict_access_to": ["0.0.0.0/0"],
                    "health_check_path": "/elb-check"
                }
            },
            "DummyRunSidekiqsh": {
                "memory_reservation": 1000,
                "command": "./run-sidekiq.sh"
            }
        }
    }

def mocked_fargate_service_config(cls, *args, **kwargs):
    return {
        "cloudlift_version": VERSION,
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


def mocked_environment_config(cls, *args, **kwargs):
    return {
        "VAR1": "val1"
    }


def mocked_service_information(cls, *args, **kwargs):
    return "master"


class TestServiceTemplateGenerator(object):
    def test_initialization(self):
        with patch.object(ServiceConfiguration, 'get_config', new=mocked_service_config):
            with patch.object(ServiceInformationFetcher, 'get_current_version', new=mocked_service_information):
                service_config = ServiceConfiguration("test-service", "staging")
                generator = ServiceTemplateGenerator(service_config, None)
                assert generator.env == 'staging'
                assert generator.application_name == 'test-service'
                assert generator.environment_stack == None

    def test_generate_service(self):
        environment = 'staging'
        application_name = 'dummy'
        env_stack = {u'StackId': 'arn:aws:cloudformation:ap-south-1:725827686899:stack/cluster-staging/65410f80-d21c-11e8-913a-503a56826a2a', u'LastUpdatedTime': datetime.datetime(2018, 11, 9, 5, 22, 30, 691000), u'Parameters': [{u'ParameterValue': 'staging-cluster-v3', u'ParameterKey': 'KeyPair'}, {u'ParameterValue': '1', u'ParameterKey': 'ClusterSize'}, {u'ParameterValue': 'arn:aws:sns:ap-south-1:725827686899:non-prod-mumbai', u'ParameterKey': 'NotificationSnsArn'}, {u'ParameterValue': 'staging', u'ParameterKey': 'Environment'}, {u'ParameterValue': 'm5.xlarge', u'ParameterKey': 'InstanceType'}, {u'ParameterValue': '50', u'ParameterKey': 'MaxSize'}], u'Tags': [], u'Outputs': [{u'Description': 'VPC in which environment is setup', u'OutputKey': 'VPC', u'OutputValue': 'vpc-00f07c5a6b6c9abdb'}, {u'Description': 'Options used with cloudlift when building this cluster', u'OutputKey': 'CloudliftOptions', u'OutputValue': '{"min_instances": 1, "key_name": "staging-cluster-v3", "max_instances": 50, "instance_type": "m5.xlarge", "cloudlift_version": "0.9.4", "env": "staging"}'}, {u'Description': 'Maximum instances in cluster', u'OutputKey': 'MaxInstances', u'OutputValue': '50'}, {u'Description': 'Security group ID for ALB', u'OutputKey': 'SecurityGroupAlb', u'OutputValue': 'sg-095dbeb511019cfd8'}, {u'Description': 'Key Pair name for accessing the instances', u'OutputKey': 'KeyName', u'OutputValue': 'staging-cluster-v3'}, {
            u'Description': 'ID of the 1st subnet', u'OutputKey': 'PrivateSubnet1', u'OutputValue': 'subnet-09b6cd23af94861cc'}, {u'Description': 'ID of the 2nd subnet', u'OutputKey': 'PrivateSubnet2', u'OutputValue': 'subnet-0657bc2faa99ce5f7'}, {u'Description': 'Minimum instances in cluster', u'OutputKey': 'MinInstances', u'OutputValue': '1'}, {u'Description': 'ID of the 2nd subnet', u'OutputKey': 'PublicSubnet2', u'OutputValue': 'subnet-096377a44ccb73aca'}, {u'Description': 'EC2 instance type', u'OutputKey': 'InstanceType', u'OutputValue': 'm5.xlarge'}, {u'Description': 'ID of the 1st subnet', u'OutputKey': 'PublicSubnet1', u'OutputValue': 'subnet-0aeae8fe5e13a7ff7'}, {u'Description': 'The name of the stack', u'OutputKey': 'StackName', u'OutputValue': 'cluster-staging'}, {u'Description': 'The unique ID of the stack. To be supplied to circle CI environment variables to validate during deployment.', u'OutputKey': 'StackId', u'OutputValue': 'arn:aws:cloudformation:ap-south-1:725827686899:stack/cluster-staging/65410f80-d21c-11e8-913a-503a56826a2a'}], u'CreationTime': datetime.datetime(2018, 10, 17, 14, 53, 23, 469000), u'Capabilities': ['CAPABILITY_NAMED_IAM'], u'StackName': 'cluster-staging', u'NotificationARNs': [], u'StackStatus': 'UPDATE_COMPLETE', u'DisableRollback': True, u'ChangeSetId': 'arn:aws:cloudformation:ap-south-1:725827686899:changeSet/cg901a2f5dbf984b9e9807a21da1ac7d12/7588cd05-1e2d-4dd6-85ab-12b921baa814', u'RollbackConfiguration': {}}

        with patch.object(ServiceConfiguration, 'get_config', new=mocked_service_config):
            with patch.object(ParameterStore, 'get_existing_config', new=mocked_environment_config):
                with patch.object(ServiceInformationFetcher, 'get_current_version', new=mocked_service_information):
                    service_config = ServiceConfiguration(application_name, environment)
                    template_generator = ServiceTemplateGenerator(service_config, env_stack)
                    template_generator.env_sample_file_path = './test/templates/test_env.sample'
                    generated_template = template_generator.generate_service()

        assert to_json(''.join(open('./test/templates/expected_service_template.yml').readlines())) == to_json(generated_template)

    def test_generate_fargate_service(self):
        environment = 'staging'
        application_name = 'dummyFargate'
        env_stack = {u'StackId': 'arn:aws:cloudformation:ap-south-1:725827686899:stack/cluster-staging/65410f80-d21c-11e8-913a-503a56826a2a', u'LastUpdatedTime': datetime.datetime(2018, 11, 9, 5, 22, 30, 691000), u'Parameters': [{u'ParameterValue': 'staging-cluster-v3', u'ParameterKey': 'KeyPair'}, {u'ParameterValue': '1', u'ParameterKey': 'ClusterSize'}, {u'ParameterValue': 'arn:aws:sns:ap-south-1:725827686899:non-prod-mumbai', u'ParameterKey': 'NotificationSnsArn'}, {u'ParameterValue': 'staging', u'ParameterKey': 'Environment'}, {u'ParameterValue': 'm5.xlarge', u'ParameterKey': 'InstanceType'}, {u'ParameterValue': '50', u'ParameterKey': 'MaxSize'}], u'Tags': [], u'Outputs': [{u'Description': 'VPC in which environment is setup', u'OutputKey': 'VPC', u'OutputValue': 'vpc-00f07c5a6b6c9abdb'}, {u'Description': 'Options used with cloudlift when building this cluster', u'OutputKey': 'CloudliftOptions', u'OutputValue': '{"min_instances": 1, "key_name": "staging-cluster-v3", "max_instances": 50, "instance_type": "m5.xlarge", "cloudlift_version": "0.9.4", "env": "staging"}'}, {u'Description': 'Maximum instances in cluster', u'OutputKey': 'MaxInstances', u'OutputValue': '50'}, {u'Description': 'Security group ID for ALB', u'OutputKey': 'SecurityGroupAlb', u'OutputValue': 'sg-095dbeb511019cfd8'}, {u'Description': 'Key Pair name for accessing the instances', u'OutputKey': 'KeyName', u'OutputValue': 'staging-cluster-v3'}, {
            u'Description': 'ID of the 1st subnet', u'OutputKey': 'PrivateSubnet1', u'OutputValue': 'subnet-09b6cd23af94861cc'}, {u'Description': 'ID of the 2nd subnet', u'OutputKey': 'PrivateSubnet2', u'OutputValue': 'subnet-0657bc2faa99ce5f7'}, {u'Description': 'Minimum instances in cluster', u'OutputKey': 'MinInstances', u'OutputValue': '1'}, {u'Description': 'ID of the 2nd subnet', u'OutputKey': 'PublicSubnet2', u'OutputValue': 'subnet-096377a44ccb73aca'}, {u'Description': 'EC2 instance type', u'OutputKey': 'InstanceType', u'OutputValue': 'm5.xlarge'}, {u'Description': 'ID of the 1st subnet', u'OutputKey': 'PublicSubnet1', u'OutputValue': 'subnet-0aeae8fe5e13a7ff7'}, {u'Description': 'The name of the stack', u'OutputKey': 'StackName', u'OutputValue': 'cluster-staging'}, {u'Description': 'The unique ID of the stack. To be supplied to circle CI environment variables to validate during deployment.', u'OutputKey': 'StackId', u'OutputValue': 'arn:aws:cloudformation:ap-south-1:725827686899:stack/cluster-staging/65410f80-d21c-11e8-913a-503a56826a2a'}], u'CreationTime': datetime.datetime(2018, 10, 17, 14, 53, 23, 469000), u'Capabilities': ['CAPABILITY_NAMED_IAM'], u'StackName': 'cluster-staging', u'NotificationARNs': [], u'StackStatus': 'UPDATE_COMPLETE', u'DisableRollback': True, u'ChangeSetId': 'arn:aws:cloudformation:ap-south-1:725827686899:changeSet/cg901a2f5dbf984b9e9807a21da1ac7d12/7588cd05-1e2d-4dd6-85ab-12b921baa814', u'RollbackConfiguration': {}}

        with patch.object(ServiceConfiguration, 'get_config', new=mocked_fargate_service_config):
            with patch.object(ParameterStore, 'get_existing_config', new=mocked_environment_config):
                with patch.object(ServiceInformationFetcher, 'get_current_version', new=mocked_service_information):
                    service_config = ServiceConfiguration(application_name, environment)
                    template_generator = ServiceTemplateGenerator(service_config, env_stack)
                    template_generator.env_sample_file_path = './test/templates/test_env.sample'
                    generated_template = template_generator.generate_service()

        assert to_json(''.join(open('./test/templates/expected_fargate_service_template.yml').readlines())) == to_json(generated_template)
