import datetime
import unittest
import os
import pytest

from cloudlift.deployment.service_information_fetcher import ServiceInformationFetcher
from cloudlift.exceptions import UnrecoverableException
from dateutil.tz import tzutc
from mock import patch, MagicMock

service = "dummy"
env = "test"


class TestServiceInformationFetcher(unittest.TestCase):

    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_fetch_service_cfn_info(self, mock_get_client_for):
        service_configuration = {
            'ecr_repo': {'name': 'dummy-repo'},
            'services': {
                'ServiceOne': {'secrets_name': 'dummy-test'},
                'ServiceTwo': {'secrets_name': 'dummy-test'},
            }
        }
        mock_cfn_client = MagicMock()
        mock_get_client_for.return_value = mock_cfn_client
        mock_cfn_client.describe_stacks.return_value = _describe_stacks_output()

        sif = ServiceInformationFetcher(service, env, service_configuration)

        expected_service_info = {
            'ServiceTwo': {'ecs_service_name': 'dummy-sen-test-ServiceTwo-45E0C5QX2HUV',
                           'secrets_name': 'dummy-test'},
            'ServiceOne': {'ecs_service_name': 'dummy-sen-test-ServiceOne-X9NCSHOSMM5S',
                           'secrets_name': 'dummy-test'}}
        self.assertDictEqual(expected_service_info, sif.service_info)
        mock_cfn_client.describe_stacks.assert_called_once_with(StackName='dummy-test')

    @patch('cloudlift.deployment.service_information_fetcher.get_region_for_environment')
    @patch('cloudlift.deployment.service_information_fetcher.EcsClient')
    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_fetch_current_desired_count(self, mock_get_client_for, mock_ecs_client, mock_get_region_for_environment):
        service_configuration = {
            'ecr_repo': {'name': 'dummy-repo'},
            'services': {
                'ServiceOne': {'secrets_name': 'dummy-test'},
                'ServiceTwo': {'secrets_name': 'dummy-test'},
            }
        }
        mock_cfn_client = MagicMock()
        mock_get_client_for.return_value = mock_cfn_client
        mock_cfn_client.describe_stacks.return_value = _describe_stacks_output()

        mock_get_region_for_environment.return_value = "mock-region"
        mock_ecs_client.return_value = mock_ecs_client
        mock_ecs_client.describe_services.return_value = {'services': [{'desiredCount': 1}]}

        sif = ServiceInformationFetcher(service, env, service_configuration)

        actual = sif.fetch_current_desired_count()
        expected = {'ServiceOne': 1, 'ServiceTwo': 1}

        self.assertEqual(expected, actual)

    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_fetch_current_image_uri(self, mock_client):
        mock_client.return_value = mock_client

        with self.subTest("when all services configurations are present"):
            service_configuration = {
                'ecr_repo': {'name': 'dummy-repo'},
                'services': {
                    'ServiceOne': {'ecs_service_name': 'service1'},
                    'ServiceTwo': {'ecs_service_name': 'service2'},
                }
            }

            mock_client.describe_services.return_value = {
                'services': [{'taskDefinition': 'tdArn1'}]}
            mock_client.describe_task_definition.return_value = {'taskDefinition': {
                'containerDefinitions': [{'image': 'image:v1'}]
            }}

            sif = ServiceInformationFetcher(
                service, env, service_configuration)

            actual = sif._fetch_current_image_uri()
            expected = "image:v1"

            self.assertEqual(expected, actual)
            mock_client.describe_task_definition.assert_called_with(
                taskDefinition='tdArn1')

        with self.subTest("when few services configurations are present"):
            service_configuration = {
                'ecr_repo': {'name': 'dummy-repo'},
                'services': {
                    'ServiceOne': {},
                    'ServiceTwo': {'ecs_service_name': 'service2'},
                }
            }

            mock_client.describe_services.return_value = {
                'services': [{'taskDefinition': 'tdArn1'}]}
            mock_client.describe_task_definition.return_value = {'taskDefinition': {
                'containerDefinitions': [{'image': 'image:v1'}]
            }}

            sif = ServiceInformationFetcher(
                service, env, service_configuration)

            actual = sif._fetch_current_image_uri()
            expected = "image:v1"

            self.assertEqual(expected, actual)
            mock_client.describe_services.assert_called_with(
                cluster="cluster-test",
                services=["service2"],
            )

        with self.subTest("raises exception if service is not present"):
            service_configuration = {
                'ecr_repo': {'name': 'dummy-repo'},
                'services': {
                    'ServiceOne': {},
                    'ServiceTwo': {'ecs_service_name': 'service2'},
                }
            }

            mock_client.describe_services.side_effect = Exception()
            sif = ServiceInformationFetcher(
                service, env, service_configuration)

            with self.assertRaises(Exception):
                sif._fetch_current_image_uri()

    @patch('cloudlift.deployment.service_information_fetcher.get_region_for_environment')
    @patch('cloudlift.deployment.service_information_fetcher.EcsClient')
    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_fetch_current_desired_count_when_stack_does_not_have_service(self, mock_get_client_for, mock_ecs_client,
                                                                          mock_get_region_for_environment):
        service_configuration = {
            'ecr_repo': {'name': 'dummy-repo'},
            'services': {
                'ServiceOne': {'secrets_name': 'dummy-test'},
                'ServiceTwo': {'secrets_name': 'dummy-test'},
            }
        }
        mock_cfn_client = MagicMock()
        mock_get_client_for.return_value = mock_cfn_client
        response = _describe_stacks_output()
        stacks = response['Stacks']
        outputs = stacks[0].get('Outputs')
        new_outputs = []
        for output in outputs:
            if output.get('OutputKey') == 'ServiceTwoEcsServiceName':
                continue
            new_outputs.append(output)
        stacks[0]['Outputs'] = new_outputs
        mock_cfn_client.describe_stacks.return_value = {'Stacks': stacks}

        mock_get_region_for_environment.return_value = "mock-region"
        mock_ecs_client.return_value = mock_ecs_client
        mock_ecs_client.describe_services.return_value = {'services': [{'desiredCount': 1}]}

        sif = ServiceInformationFetcher(service, env, service_configuration)
        def return_for_only_one_service(cluster_name, service_name):
            if service_name == 'dummy-sen-test-ServiceOne-X9NCSHOSMM5S':
                return {'services': [{'desiredCount': 1}]}
            raise Exception()

        mock_ecs_client.describe_services.side_effect = return_for_only_one_service

        actual = sif.fetch_current_desired_count()
        expected = {'ServiceOne': 1}
        self.assertEqual(expected, actual)

    @patch('builtins.print')
    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_get_version(self, mock_get_client_for, mock_print):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client
        mock_client.describe_stacks.return_value = _describe_stacks_output_with_ecr_repo_config()
        mock_client.describe_services.return_value = {'services': [{'taskDefinition': 'arn1'}]}
        mock_client.describe_task_definition.return_value = {'taskDefinition': {
            'containerDefinitions': [{'image': 'repo:v1-12345'}],
        }}

        sif = ServiceInformationFetcher(service, env, _service_configuration())

        sif.get_version()

        mock_print.assert_called_with('v1-12345')

    @patch('builtins.print')
    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_get_version_with_image(self, mock_get_client_for, mock_print):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client
        mock_client.describe_stacks.return_value = _describe_stacks_output_with_ecr_repo_config()
        mock_client.describe_services.return_value = {'services': [{'taskDefinition': 'arn1'}]}
        mock_client.describe_task_definition.return_value = {'taskDefinition': {
            'containerDefinitions': [{'image': 'repo:v1-12345'}],
        }}

        sif = ServiceInformationFetcher(service, env, _service_configuration())

        sif.get_version(print_image=True)

        mock_print.assert_called_with('repo:v1-12345')

    @patch('builtins.print')
    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_get_version_with_git(self, mock_get_client_for, mock_print):
        mock_client = MagicMock()
        mock_get_client_for.return_value = mock_client
        mock_client.describe_stacks.return_value = _describe_stacks_output_with_ecr_repo_config()
        mock_client.describe_services.return_value = {'services': [{'taskDefinition': 'arn1'}]}
        mock_client.describe_task_definition.return_value = {'taskDefinition': {
            'containerDefinitions': [{'image': 'repo:fedbdf-12345'}],
        }}

        sif = ServiceInformationFetcher(service, env, _service_configuration())

        sif.get_version(print_git=True)

        mock_print.assert_called_with('fedbdf')

    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_initialization_from_service_configuration(self, mock_get_client_for):
        mock_get_client_for.return_value.describe_stacks.return_value = _describe_stacks_output_with_ecr_repo_config()
        sif = ServiceInformationFetcher(service, env, _service_configuration())

        expected_service_info = {
            'ServiceOne': {
                'ecs_service_name': 'dummy-sen-test-ServiceOne-X9NCSHOSMM5S',
                'secrets_name': 'dummy-test',
            },
            'ServiceTwo': {
                'ecs_service_name': 'generated-ecs-service',
                'secrets_name': 'dummy-test2',
            },
        }

        self.assertEqual(expected_service_info, sif.service_info)

    @patch('cloudlift.deployment.deployer.secrets_manager')
    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_verify_env_sample_success(self, mock_get_client_for, mock_secrets_manager):
        mock_get_client_for.return_value.describe_stacks.return_value = _describe_stacks_output_with_ecr_repo_config()

        def get_config(secret_name, env):
            if secret_name in {'dummy-test', 'dummy-test2'}:
                return {'secrets': {
                        'key1': 'actualValue1',
                        'key2': 'actualValue2',
                        'key3': 'actualValue3',
                    }}
            if secret_name in {'dummy-test/app1', 'dummy-test2/app1'}:
                return {'secrets': {
                    'key4': 'actualValue4',
                    'key5': 'actualValue5',
                }}
            raise Exception('not found')
        mock_secrets_manager.get_config.side_effect = get_config

        sif = ServiceInformationFetcher(service, env, _service_configuration())

        env_sample_directory_path = os.path.join(
            os.path.dirname(__file__),
            '../env_sample_files/env_sample_files_without_duplicate_keys',
        )

        # should not raise
        sif.verify_env_sample(env_sample_directory_path)

        self.assertEqual(mock_secrets_manager.get_config.call_count, 4)

    @patch('cloudlift.deployment.deployer.secrets_manager')
    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_verify_env_sample_fail_duplicate_entries(self, mock_get_client_for, mock_secrets_manager):
        mock_get_client_for.return_value.describe_stacks.return_value = _describe_stacks_output_with_ecr_repo_config()

        def get_config(secret_name, env):
            if secret_name in {'dummy-test', 'dummy-test2'}:
                return {'secrets': {
                        'key1': 'actualValue1',
                        'key2': 'actualValue2',
                        'key3': 'actualValue3',
                    }}
            if secret_name in {'dummy-test/app1', 'dummy-test2/app1'}:
                return {'secrets': {
                    'key4': 'actualValue4',
                    'key5': 'actualValue5',
                }}
            raise Exception('not found')
        mock_secrets_manager.get_config.side_effect = get_config

        sif = ServiceInformationFetcher(service, env, _service_configuration())

        env_sample_directory_path = os.path.join(
            os.path.dirname(__file__),
            '../env_sample_files/env_sample_files_with_duplicate_keys',
        )


        with pytest.raises(UnrecoverableException) as pytest_wrapped_e:
            sif.verify_env_sample(env_sample_directory_path)

        self.assertEqual(pytest_wrapped_e.type, UnrecoverableException)
        self.assertEqual(str(pytest_wrapped_e.value),
                         "\"duplicate keys found in env sample files [({'key1'}, 'env.app1.sample')] \"")

    @patch('cloudlift.deployment.deployer.secrets_manager')
    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_verify_env_sample_fail_missing_entries(self, mock_get_client_for, mock_secrets_manager):
        mock_get_client_for.return_value.describe_stacks.return_value = _describe_stacks_output_with_ecr_repo_config()

        def get_config(secret_name, env):
            if secret_name in {'dummy-test', 'dummy-test2'}:
                return {'secrets': {
                        'key1': 'actualValue1',
                        # 'key2': 'actualValue2',  #missing value
                        'key3': 'actualValue3',
                    }}
            if secret_name in {'dummy-test/app1', 'dummy-test2/app1'}:
                return {'secrets': {
                    'key4': 'actualValue4',
                    'key5': 'actualValue5',
                }}
            raise Exception('not found')
        mock_secrets_manager.get_config.side_effect = get_config

        sif = ServiceInformationFetcher(service, env, _service_configuration())

        env_sample_directory_path = os.path.join(
            os.path.dirname(__file__),
            '../env_sample_files/env_sample_files_without_duplicate_keys',
        )


        with pytest.raises(UnrecoverableException) as pytest_wrapped_e:
            sif.verify_env_sample(env_sample_directory_path)

        self.assertEqual(pytest_wrapped_e.type, UnrecoverableException)
        self.assertEqual(str(pytest_wrapped_e.value), "\"There is no config value for the keys {'key2'}\"")


def _describe_stacks_output():
    return {'Stacks': [{
        'StackId': 'arn:aws:cloudformation:us-west-2:408750594584:stack/dummy-sen-test/3eeaa640-edcf-11ea-9f4d-0a3d9b1fa9c6',
        'StackName': 'dummy-sen-test',
        'ChangeSetId': 'arn:aws:cloudformation:us-west-2:408750594584:changeSet/cg5a9497656c6f4aa9ad85ebf52f780e74/9960c130-8b0f-4723-9620-4463958ead22',
        'Parameters': [{'ParameterKey': 'PrivateSubnet1', 'ParameterValue': 'subnet-0643ce156e953606c'},
                       {'ParameterKey': 'PrivateSubnet2', 'ParameterValue': 'subnet-0906ebb9dea7889ad'},
                       {'ParameterKey': 'NotificationSnsArn',
                        'ParameterValue': 'arn:aws:sns:us-west-2:408750594584:cloudlift-test-env'},
                       {'ParameterKey': 'VPC', 'ParameterValue': 'vpc-0adf6f906ae3c4ddd'},
                       {'ParameterKey': 'Environment', 'ParameterValue': 'test'},
                       {'ParameterKey': 'PublicSubnet2', 'ParameterValue': 'subnet-00bd6c058d51ffcd2'},
                       {'ParameterKey': 'PublicSubnet1', 'ParameterValue': 'subnet-0bcbd1e259c556d3e'}],
        'CreationTime': datetime.datetime(2020, 9, 3, 10, 21, 35, 930000, tzinfo=tzutc()),
        'LastUpdatedTime': datetime.datetime(2020, 9, 5, 14, 7, 14, 223000, tzinfo=tzutc()),
        'RollbackConfiguration': {}, 'StackStatus': 'UPDATE_COMPLETE', 'DisableRollback': True,
        'NotificationARNs': [], 'Capabilities': ['CAPABILITY_NAMED_IAM'], 'Outputs': [
            {'OutputKey': 'ServiceOneURL',
             'OutputValue': 'https://ServiceOneTest-1906403531.us-west-2.elb.amazonaws.com',
             'Description': 'The URL at which the service is accessible'},
            {'OutputKey': 'ServiceOneSecretsName', 'OutputValue': 'dummy-test',
             'Description': 'AWS secrets manager name to pull the secrets from'},
            {'OutputKey': 'ServiceTwoEcsServiceName', 'OutputValue': 'dummy-sen-test-ServiceTwo-45E0C5QX2HUV',
             'Description': 'The ECS name which needs to be entered'}, {'OutputKey': 'CloudliftOptions',
                                                                        'OutputValue': '{"services": {"ServiceTwo": {"system_controls": [], "memory_reservation": 700, "command": null, "http_interface": {"restrict_access_to": ["0.0.0.0/0"], "container_port": 80, "internal": false, "health_check_path": "/elb-check", "alb": {"create_new": true}}}, "ServiceOne": {"system_controls": [], "memory_reservation": 700, "command": null, "http_interface": {"restrict_access_to": ["0.0.0.0/0"], "container_port": 80, "internal": false, "health_check_path": "/elb-check", "alb": {"create_new": true}}, "secrets_name": "dummy"}}}',
                                                                        'Description': 'Options used with cloudlift when building this service'},
            {'OutputKey': 'ServiceTwoURL',
             'OutputValue': 'https://ServiceTwoTest-707380103.us-west-2.elb.amazonaws.com',
             'Description': 'The URL at which the service is accessible'},
            {'OutputKey': 'StackName', 'OutputValue': 'dummy-sen-test', 'Description': 'The name of the stack'},
            {'OutputKey': 'ServiceTwoSecretsName', 'OutputValue': 'dummy-test',
             'Description': 'AWS secrets manager name to pull the secrets from'},
            {'OutputKey': 'ServiceOneEcsServiceName', 'OutputValue': 'dummy-sen-test-ServiceOne-X9NCSHOSMM5S',
             'Description': 'The ECS name which needs to be entered'}, {'OutputKey': 'StackId',
                                                                        'OutputValue': 'arn:aws:cloudformation:us-west-2:408750594584:stack/dummy-sen-test/3eeaa640-edcf-11ea-9f4d-0a3d9b1fa9c6',
                                                                        'Description': 'The unique ID of the stack. To be supplied to circle CI environment variables to validate during deployment.'},
            {'OutputKey': 'ECRRepoName', 'OutputValue': 'dummy-sen-repo'}
        ],
        'Tags': [], 'EnableTerminationProtection': False,
        'DriftInformation': {'StackDriftStatus': 'NOT_CHECKED'}}]}


def _service_configuration():
    return {
        'ecr_repo': {'name': 'dummy-repo'},
        'services': {
            'ServiceOne': {'secrets_name': 'dummy-test'},
            'ServiceTwo': {'ecs_service_name': 'generated-ecs-service', 'secrets_name': 'dummy-test2'},
        }
    }


def _describe_stacks_output_with_ecr_repo_config():
    stack_configs = _describe_stacks_output()
    assert len(stack_configs.get('Stacks', [])) == 1
    outputs = stack_configs['Stacks'][0].get('Outputs', [])
    outputs.append({'OutputKey': 'ECRAssumeRoleARN', 'OutputValue': 'test-assume-role-arn'})
    outputs.append({'OutputKey': 'ECRAccountID', 'OutputValue': '12345'})
    stack_configs['Stacks'][0]['Outputs'] = outputs
    return stack_configs
