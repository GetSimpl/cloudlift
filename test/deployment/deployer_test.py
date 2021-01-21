import os
from _datetime import datetime, timedelta
from copy import deepcopy
from unittest import TestCase
from unittest.mock import patch, MagicMock, sentinel, mock_open

import pytest
from dateutil.tz.tz import tzlocal

from cloudlift.deployment.deployer import is_deployed, \
    record_deployment_failure_metric, deploy_and_wait, build_config, get_env_sample_file_name, \
    get_env_sample_file_contents, get_namespaces_from_directory, find_duplicate_keys, get_sample_keys, get_secret_name, \
    get_automated_injected_secret_name, create_new_task_definition
from cloudlift.deployment.ecs import EcsService, EcsTaskDefinition
from cloudlift.exceptions import UnrecoverableException


class TestDeployer(TestCase):
    def test_is_deployed_returning_true_if_desiredCount_equals_runningCount(self):
        service = {
            "desiredCount": 201,
            "runningCount": 201,
            "pendingCount": 0,
            "deployments": [
                {'id': 'ecs-svc/1234567891012345679', 'status': 'PRIMARY',
                 'taskDefinition': 'arn:aws:ecs:us-west-2:123456789101:task-definition/SuperTaskFamily:513',
                 'desiredCount': 201, 'pendingCount': 0, 'runningCount': 201,
                 'createdAt': datetime.now(), 'updatedAt': datetime.now(), 'launchType': 'EC2'}
            ]
        }
        assert is_deployed(service)

    def test_is_deployed_false_if_desiredCount_not_equals_runningCount(self):
        service = {
            "desiredCount": 201,
            "runningCount": 200,
            "pendingCount": 1,
            "deployments": [
                {'id': 'ecs-svc/1234567891012345679', 'status': 'PRIMARY',
                 'taskDefinition': 'arn:aws:ecs:us-west-2:123456789101:task-definition/SuperTaskFamily:513',
                 'desiredCount': 201, 'pendingCount': 1, 'runningCount': 200,
                 'createdAt': datetime.now(), 'updatedAt': datetime.now(), 'launchType': 'EC2'}
            ]
        }
        assert not is_deployed(service)

    def test_is_deployed_false_for_multiple_deployments(self):
        service = {
            "desiredCount": 201,
            "pendingCount": 0,
            "runningCount": 401,
            "deployments": [
                {'id': 'ecs-svc/1234567891012345679', 'status': 'ACTIVE',
                 'taskDefinition': 'arn:aws:ecs:us-west-2:123456789101:task-definition/SuperTaskFamily:513',
                 'desiredCount': 201, 'pendingCount': 0, 'runningCount': 201,
                 'createdAt': datetime.now(), 'updatedAt': datetime.now(), 'launchType': 'EC2'},
                {'id': 'ecs-svc/1234567891012345679', 'status': 'PRIMARY',
                 'taskDefinition': 'arn:aws:ecs:us-west-2:123456789101:task-definition/SuperTaskFamily:513',
                 'desiredCount': 201, 'pendingCount': 1, 'runningCount': 200,
                 'createdAt': datetime.now(), 'updatedAt': datetime.now(), 'launchType': 'EC2'},
            ]
        }
        assert not is_deployed(service)

    def test_is_deployed_false_for_multiple_deployments_when_desired_count_is_running_count(self):
        service = {
            "desiredCount": 201,
            "pendingCount": 100,
            "runningCount": 201,
            "deployments": [
                {'id': 'ecs-svc/1234567891012345679', 'status': 'PRIMARY',
                 'taskDefinition': 'arn:aws:ecs:us-west-2:123456789101:task-definition/SuperTaskFamily:513',
                 'desiredCount': 201, 'pendingCount': 100, 'runningCount': 101,
                 'createdAt': datetime.now(), 'updatedAt': datetime.now(), 'launchType': 'EC2'},
                {'id': 'ecs-svc/1234567891012345679', 'status': 'ACTIVE',
                 'taskDefinition': 'arn:aws:ecs:us-west-2:123456789101:task-definition/SuperTaskFamily:513',
                 'desiredCount': 100, 'pendingCount': 0, 'runningCount': 100,
                 'createdAt': datetime.now(), 'updatedAt': datetime.now(), 'launchType': 'EC2'},
            ]
        }
        assert not is_deployed(service)

    @patch("cloudlift.deployment.deployer.build_config")
    def test_create_new_task_definition(self, mock_build_config):
        client = MagicMock()
        service_configuration = {
            'command': './start_script.sh',
            'container_health_check': {
                'command': './check-health.sh',
                'start_period': 10
            },
            'memory_reservation': 100,
        }
        mock_build_config.return_value = {
            'DummyContainer': {
                "secrets": {"CLOUDLIFT_INJECTED_SECRETS": 'arn_injected_secrets'},
                "environment": {"PORT": "80"}
            },
        }

        current_task_definition = {
            'containerDefinitions': [
                {
                    'environment': [{'name': 'PORT', 'value': '80'}],
                    'secrets': [{'name': 'CLOUDLIFT_INJECTED_SECRETS', 'valueFrom': 'arn_injected_secrets'}],
                    'name': 'DummyContainer',
                    'image': 'nginx:v1',
                    'essential': True,
                    'logConfiguration': {'logDriver': 'awslogs',
                                         'options': {'awslogs-stream-prefix': 'Dummy', 'awslogs-group': 'test-logs',
                                                     'awslogs-region': 'region1'}},
                    'memoryReservation': 100, 'cpu': 0, 'command': ['./start_script.sh'],
                    'healthCheck': {'command': ['CMD-SHELL', './check-health.sh'], 'startPeriod': 10},
                }
            ],
            'executionRoleArn': 'oldTaskExecRoleArn',
            'family': 'testDummyFamily',
            'placementConstraints': [],
            'taskRoleArn': 'oldTaskRoleArn',
            'tags': [{'key': 'deployment_identifier', 'value': 'id-00'}],
        }

        expected = deepcopy(current_task_definition)
        expected['containerDefinitions'][0]['image'] = 'nginx:v2'
        expected['tags'][0]['value'] = 'id-01'
        expected['containerDefinitions'][0]['memory'] = 20480

        client.describe_services.return_value = {'services': [{
            'taskDefinition': 'tdARN1',
        }]}
        client.describe_task_definition.return_value = {
            'taskDefinition': current_task_definition,
            'tags': [{'key': 'deployment_identifier', 'value': 'id-00'}],
        }
        create_new_task_definition(
            color='white',
            client=client,
            cluster_name='cluster-test',
            ecs_service_name='dummy-123',
            ecs_service_logical_name='Dummy',
            deployment_identifier='id-01',
            service_name='dummy-test',
            sample_env_file_path='./env.sample',
            env_name='test',
            secrets_name='dummy-test-secrets',
            service_configuration=service_configuration,
            region='region1',
            ecr_image_uri='nginx:v2',
        )

        client.describe_services.assert_called_with(cluster_name='cluster-test', service_name='dummy-123')
        client.describe_task_definition.assert_called_with(task_definition_arn='tdARN1')
        args, kwargs = client.register_task_definition.call_args
        self.assertEqual(expected, kwargs)
        client.register_task_definition.assert_called_with(**expected)


class TestDeployAndWait(TestCase):
    @staticmethod
    def create_ecs_service_with_status(status):
        return EcsService('cluster-testing', status)

    def test_deploy_and_wait_successful_run(self):
        deployment = MagicMock()
        deployment.get_service.side_effect = [
            self.create_ecs_service_with_status({
                'desiredCount': 5,
                'runningCount': 0,
                'events': [
                    {'message': 'event1', 'createdAt': datetime.now()}
                ],
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 0}
                ]
            }),
            self.create_ecs_service_with_status({
                'desiredCount': 5,
                'runningCount': 5,
                'events': [
                    {'message': 'service test has reached a steady state.', 'createdAt': datetime.now()}
                ],
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 5}
                ]
            })
        ]

        new_task_definition = EcsTaskDefinition({'containerDefinitions': []})
        color = "green"
        timeout_seconds = 3

        self.assertTrue(
            deploy_and_wait(deployment, new_task_definition, color, timeout_seconds),
            "expected deployment to be successful"
        )

        deployment.deploy.assert_called_with(new_task_definition)

    @patch("cloudlift.deployment.deployer.log_err")
    def test_deploy_and_wait_timeout(self, mock_log_err):
        deployment = MagicMock()
        deployment.get_service.return_value = self.create_ecs_service_with_status({
            'desiredCount': 5,
            'runningCount': 0,
            'events': [
                {'message': 'service test has reached a steady state.', 'createdAt': datetime.now()}
            ],
            'deployments': [
                {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 0}
            ]
        })

        new_task_definition = EcsTaskDefinition({'containerDefinitions': []})
        color = "green"
        timeout_seconds = 2

        self.assertFalse(
            deploy_and_wait(deployment, new_task_definition, color, timeout_seconds),
            "expected deployment to fail"
        )

        deployment.deploy.assert_called_with(new_task_definition)
        mock_log_err.assert_called_with('Deployment timed out!')

    @patch("cloudlift.deployment.deployer.log_err")
    def test_deploy_and_wait_unable_to_place_tasks_initially_succeeds_eventually(self, mock_log_err):
        deployment = MagicMock()
        start_time = datetime.now(tz=tzlocal())
        deployment.get_service.side_effect = [
            self.create_ecs_service_with_status({
                'desiredCount': 5,
                'runningCount': 0,
                'events': [
                    {'message': 'unable to place tasks due to memory', 'createdAt': start_time},
                ],
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 0,
                     'createdAt': start_time - timedelta(seconds=5),
                     'updatedAt': start_time - timedelta(seconds=5)}
                ]
            }),
            self.create_ecs_service_with_status({
                'events': [
                    {'message': 'unable to place tasks due to memory',
                     'createdAt': start_time + timedelta(seconds=1)},
                ],
                'desiredCount': 5,
                'runningCount': 0,
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 0,
                     'createdAt': start_time - timedelta(seconds=5),
                     'updatedAt': start_time - timedelta(seconds=2)}
                ]
            }),
            self.create_ecs_service_with_status({
                'desiredCount': 5,
                'runningCount': 5,
                'events': [
                    {'message': 'service test has reached a steady state.',
                     'createdAt': start_time + timedelta(seconds=2)},
                ],
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 5,
                     'createdAt': start_time - timedelta(seconds=5),
                     'updatedAt': start_time - timedelta(seconds=1)}
                ]
            }),
        ]

        new_task_definition = EcsTaskDefinition({'containerDefinitions': []})
        color = "green"
        timeout_seconds = 15

        self.assertTrue(
            deploy_and_wait(deployment, new_task_definition, color, timeout_seconds),
            "expected deployment to pass"
        )

        deployment.deploy.assert_called_with(new_task_definition)
        mock_log_err.assert_not_called()

    @patch("cloudlift.deployment.deployer.log_err")
    def test_deploy_and_wait_unable_to_place_tasks_till_timeout(self, mock_log_err):
        deployment = MagicMock()
        start_time = datetime.now(tz=tzlocal())
        deployment.get_service.side_effect = [
            self.create_ecs_service_with_status({
                'desiredCount': 5,
                'runningCount': 0,
                'events': [
                    {'message': 'unable to place tasks due to memory', 'createdAt': start_time},
                ],
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 0,
                     'createdAt': start_time - timedelta(seconds=5),
                     'updatedAt': start_time - timedelta(seconds=5)}
                ]
            }),
            self.create_ecs_service_with_status({
                'desiredCount': 5,
                'runningCount': 0,
                'events': [
                    {'message': 'unable to place tasks due to memory',
                     'createdAt': start_time + timedelta(seconds=1)},
                ],
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 0,
                     'createdAt': start_time - timedelta(seconds=5),
                     'updatedAt': start_time - timedelta(seconds=4)}
                ]
            }),
            self.create_ecs_service_with_status({
                'desiredCount': 5,
                'runningCount': 0,
                'events': [
                    {'message': 'unable to place tasks due to memory',
                     'createdAt': start_time + timedelta(seconds=2)},
                ],
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 0,
                     'createdAt': start_time - timedelta(seconds=5),
                     'updatedAt': start_time - timedelta(seconds=3)}
                ]
            }),
        ]

        new_task_definition = EcsTaskDefinition({'containerDefinitions': []})
        color = "green"
        timeout_seconds = 2

        self.assertFalse(
            deploy_and_wait(deployment, new_task_definition, color, timeout_seconds),
            "expected deployment to fail"
        )

        deployment.deploy.assert_called_with(new_task_definition)
        mock_log_err.assert_called_with('Deployment timed out!')


@patch('cloudlift.deployment.deployer.datetime')
@patch('cloudlift.deployment.deployer.boto3.client')
def test_create_deployment_timeout_alarm(mock_boto3_client, dt):
    mock_boto3_client.put_metric_data = MagicMock()
    cluster_name = sentinel.cluster_name
    service_name = sentinel.service_name
    now = datetime.now()
    dt.utcnow = MagicMock(return_value=now)
    record_deployment_failure_metric(cluster_name, service_name)
    mock_boto3_client.assert_called_with('cloudwatch')
    mock_boto3_client.return_value.put_metric_data.assert_called_with(
        Namespace='ECS/DeploymentMetrics',
        MetricData=[
            {
                "MetricName": 'FailedCloudliftDeployments',
                "Value": 1,
                "Timestamp": now,
                "Dimensions": [
                    {
                        'Name': 'ClusterName',
                        'Value': cluster_name
                    },
                    {
                        'Name': 'ServiceName',
                        'Value': service_name
                    }
                ]
            }
        ]
    )


class TestBuildConfig(TestCase):

    @patch('builtins.open', mock_open(read_data="PORT=1\nLABEL=test"))
    @patch('cloudlift.deployment.deployer.ParameterStore')
    @patch('cloudlift.deployment.deployer.secrets_manager')
    def test_successful_build_config_from_only_param_store(self, mock_secrets_manager, mock_parameter_store):
        env_name = "staging"
        cloudlift_service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        essential_container_name = "mainServiceContainer"

        mock_store = MagicMock()
        mock_parameter_store.return_value = mock_store
        mock_store.get_existing_config.return_value = ({'PORT': '80', 'LABEL': 'Dummy'}, {})

        actual_configurations = build_config(env_name, cloudlift_service_name, "", sample_env_file_path,
                                             essential_container_name, None)

        expected_configurations = {
            "mainServiceContainer": {
                "environment": {"LABEL": "Dummy", "PORT": "80"},
                "secrets": {}
            }
        }
        self.assertDictEqual(expected_configurations, actual_configurations)
        mock_secrets_manager.get_config.assert_not_called()

    @patch('builtins.open', mock_open(read_data="PORT=1\nLABEL=test"))
    @patch('cloudlift.deployment.deployer.ParameterStore')
    @patch('cloudlift.deployment.deployer.secrets_manager')
    def test_successful_build_config_from_without_duplicates(self, mock_secrets_manager, mock_parameter_store):
        env_name = "staging"
        cloudlift_service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        essential_container_name = "mainService"
        secrets_name = "main"
        mock_store = MagicMock()
        mock_parameter_store.return_value = mock_store
        mock_store.get_existing_config.return_value = (
            {'PORT': '80', "LABEL": "arn_for_secret_at_v1"}, {})
        mock_secrets_manager.get_config.return_value = {}

        actual_configurations = build_config(env_name, cloudlift_service_name, "", sample_env_file_path,
                                             essential_container_name, None)

        expected_configurations = {
            "mainService": {
                "secrets": {},
                "environment": {"PORT": "80", "LABEL": "arn_for_secret_at_v1"}
            }
        }
        self.assertDictEqual(expected_configurations, actual_configurations)

    @patch('builtins.open', mock_open(read_data="PORT=1\nLABEL=test\nADDITIONAL_CONFIG=true"))
    @patch('cloudlift.deployment.deployer.ParameterStore')
    @patch('cloudlift.deployment.deployer.secrets_manager')
    def test_failure_build_config_for_if_sample_config_has_additional_keys(self, m_secrets_manager,
                                                                           m_parameter_store):
        env_name = "staging"
        service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        essential_container_name = "mainService"
        mock_store = MagicMock()
        m_parameter_store.return_value = mock_store
        mock_store.get_existing_config.return_value = ({'PORT': '80', "LABEL": "arn_for_secret_at_v1"}, {})
        m_secrets_manager.get_config.return_value = {}

        with pytest.raises(UnrecoverableException) as pytest_wrapped_e:
            build_config(env_name, service_name, "", sample_env_file_path, essential_container_name, None)

        self.assertEqual(pytest_wrapped_e.type, UnrecoverableException)
        self.assertEqual(str(pytest_wrapped_e.value),
                         '"There is no config value for the keys {\'ADDITIONAL_CONFIG\'}"')

    @patch('cloudlift.deployment.deployer.ParameterStore')
    @patch('cloudlift.deployment.deployer.secrets_manager')
    @patch('os.getcwd')
    def test_build_config_for_secrets_manager_from_multiple_files(self,
                                                                  mock_getcwd,
                                                                  m_secrets_manager, m_parameter_store):
        env_name = "staging"
        service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        essential_container_name = "mainService"
        ecs_service_name = "dummy-ecs-service"
        injected_secret_name = get_automated_injected_secret_name(env_name, service_name, ecs_service_name)

        class MockSecretManager:
            injected_secret_name_call_count = 0

            @classmethod
            def get_config(cls, secret_name, env):
                if secret_name == 'dummy-secrets-staging':
                    return {'secrets': {
                        'key1': 'actualValue1',
                        'key2': 'actualValue2',
                        'key3': 'actualValue3',
                    }}
                if secret_name == 'dummy-secrets-staging/app1':
                    return {'secrets': {
                        'key4': 'actualValue4',
                        'key5': 'actualValue5',
                    }}
                if secret_name == injected_secret_name and cls.injected_secret_name_call_count == 0:
                    cls.injected_secret_name_call_count += 1
                    raise Exception('not found')
                if secret_name == injected_secret_name:
                    return {'ARN': 'injected-secret-arn'}
                return {'secrets': {}}

        m_secrets_manager.get_config.side_effect = MockSecretManager.get_config
        mock_getcwd.return_value = os.path.join(
            os.path.dirname(__file__),
            '../env_sample_files/env_sample_files_without_duplicate_keys',
        )

        result = build_config(env_name, service_name, ecs_service_name, sample_env_file_path,
                              essential_container_name,
                              "dummy-secrets-staging")

        m_secrets_manager.set_secrets_manager_config.assert_called_with(
            env_name,
            injected_secret_name,
            {
                'key1': 'actualValue1',
                'key2': 'actualValue2',
                'key3': 'actualValue3',
                'key4': 'actualValue4',
            }
        )
        self.assertEqual({
            essential_container_name: {
                'environment': {},
                'secrets': {'CLOUDLIFT_INJECTED_SECRETS': 'injected-secret-arn'}}}, result)

    @patch('cloudlift.deployment.deployer.secrets_manager')
    @patch('os.getcwd')
    def test_build_config_for_secrets_manager_from_multiple_files_already_present(self,
                                                                                  mock_getcwd,
                                                                                  m_secrets_manager):
        env_name = "staging"
        service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        essential_container_name = "mainService"
        ecs_service_name = "dummy-ecs-service"
        secrets = {
            'key1': 'actualValue1',
            'key2': 'actualValue2',
            'key3': 'actualValue3',
            'key4': 'actualValue4',
        }

        def get_config(secret_name, env):
            if secret_name == 'dummy-secrets-staging':
                return {'secrets': {
                    'key1': 'actualValue1',
                    'key2': 'actualValue2',
                    'key3': 'actualValue3',
                }}
            if secret_name == 'dummy-secrets-staging/app1':
                return {'secrets': {
                    'key4': 'actualValue4',
                    'key5': 'actualValue5',
                }}
            if secret_name == get_automated_injected_secret_name(env_name, service_name, ecs_service_name):
                return {'ARN': 'injected-secret-arn', 'secrets': secrets}
            return {'secrets': {}}

        m_secrets_manager.get_config.side_effect = get_config
        mock_getcwd.return_value = os.path.join(
            os.path.dirname(__file__),
            '../env_sample_files/env_sample_files_without_duplicate_keys',
        )

        result = build_config(env_name, service_name, ecs_service_name, sample_env_file_path,
                              essential_container_name,
                              "dummy-secrets-staging")

        m_secrets_manager.set_secrets_manager_config.assert_not_called()
        self.assertEqual({
            essential_container_name: {
                'environment': {},
                'secrets': {'CLOUDLIFT_INJECTED_SECRETS': 'injected-secret-arn'}}}, result)

    @patch('builtins.open', mock_open(read_data="PORT=1\nLABEL=test"))
    @patch('cloudlift.deployment.deployer.ParameterStore')
    @patch('cloudlift.deployment.deployer.secrets_manager')
    def test_build_config_ignores_additional_keys_in_parameter_store(self, m_secrets_mgr, m_parameter_store):
        env_name = "staging"
        service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        essential_container_name = "mainService"
        secrets_name = "main"
        mock_store = MagicMock()
        m_parameter_store.return_value = mock_store
        mock_store.get_existing_config.return_value = (
            {"LABEL": "dummyvalue", 'PORT': '80', 'ADDITIONAL_KEY_1': 'true'}, {})
        m_secrets_mgr.get_config.return_value = {'secrets': {},
                                                 'ARN': "dummy_arn"}

        actual_configurations = build_config(env_name, service_name, "", sample_env_file_path,
                                             essential_container_name, None)

        expected_configurations = {
            "mainService": {
                "secrets": {},
                "environment": {"PORT": "80", "LABEL": "dummyvalue"}
            }
        }
        self.assertDictEqual(expected_configurations, actual_configurations)


class TestSecrets(TestCase):

    def test_get_env_sample_file_name_for_default_namespace(self):
        self.assertEqual(get_env_sample_file_name(''), 'env.sample')

    def test_get_env_sample_file_name_for_non_default_namespace(self):
        self.assertEqual(get_env_sample_file_name('app2'), 'env.app2.sample')

    def test_get_env_sample_file_contents(self):
        directory = os.path.join(os.path.dirname(__file__),
                                 '../env_sample_files/env_sample_files_without_duplicate_keys')
        self.assertEqual(get_env_sample_file_contents(directory, ''),
                         "key1=value1\nkey2=value2\nkey3=value3")

    def test_get_sample_keys(self):
        directory = os.path.join(os.path.dirname(__file__),
                                 '../env_sample_files/env_sample_files_without_duplicate_keys')
        self.assertEqual(get_sample_keys(directory, ''), {'key2', 'key1', 'key3'})

    def test_get_namespaces_from_directory(self):
        directory = os.path.join(os.path.dirname(__file__),
                                 '../env_sample_files/env_sample_files_without_duplicate_keys')
        self.assertEqual(get_namespaces_from_directory(directory), {'', 'app1'})

    def test_env_sample_files_with_no_duplicates(self):
        directory = os.path.join(os.path.dirname(__file__),
                                 '../env_sample_files/env_sample_files_without_duplicate_keys')
        self.assertEqual(find_duplicate_keys(directory, get_namespaces_from_directory(directory)), [])

    def test_env_sample_files_with_duplicates(self):
        directory = os.path.join(os.path.dirname(__file__),
                                 '../env_sample_files/env_sample_files_with_duplicate_keys')
        self.assertEqual(find_duplicate_keys(directory, get_namespaces_from_directory(directory)),
                         [({'key1'}, 'env.app1.sample')])

    def test_get_secret_name_for_default_execution_namespace(self):
        self.assertEqual(get_secret_name('test-prefix-test', ''), 'test-prefix-test')
        self.assertEqual(get_secret_name('test-prefix-test', None), 'test-prefix-test')

    def test_get_secret_name_for_non_default_execution_namespace(self):
        self.assertEqual(get_secret_name('test-prefix-test', 'app1'), 'test-prefix-test/app1')
