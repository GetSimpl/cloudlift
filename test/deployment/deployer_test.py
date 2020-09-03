from _datetime import datetime, timedelta
from dateutil.tz.tz import tzlocal
import pytest
from unittest import TestCase
from unittest.mock import patch, MagicMock, sentinel, mock_open
from cloudlift.deployment.deployer import is_deployed, \
    record_deployment_failure_metric, deploy_and_wait, build_config
from cloudlift.deployment.ecs import EcsService, EcsTaskDefinition
from cloudlift.exceptions import UnrecoverableException


class TestDeployer(TestCase):
    def test_is_deployed_returning_true_if_desiredCount_equals_runningCount(self):
        deployments = [
            {'id': 'ecs-svc/1234567891012345679', 'status': 'PRIMARY',
             'taskDefinition': 'arn:aws:ecs:us-west-2:123456789101:task-definition/SuperTaskFamily:513',
             'desiredCount': 201, 'pendingCount': 0, 'runningCount': 201,
             'createdAt': datetime.now(), 'updatedAt': datetime.now(), 'launchType': 'EC2'}]
        assert is_deployed(deployments)

    def test_is_deployed_returning_false_if_desiredCount_not_equals_runningCount(self):
        deployments = [
            {'id': 'ecs-svc/1234567891012345679', 'status': 'PRIMARY',
             'taskDefinition': 'arn:aws:ecs:us-west-2:123456789101:task-definition/SuperTaskFamily:513',
             'desiredCount': 201, 'pendingCount': 1, 'runningCount': 200,
             'createdAt': datetime.now(), 'updatedAt': datetime.now(), 'launchType': 'EC2'}]
        assert not is_deployed(deployments)

    def test_is_deployed_considering_only_primary_deployment(self):
        deployments = [
            {'id': 'ecs-svc/1234567891012345679', 'status': 'ACTIVE',
             'taskDefinition': 'arn:aws:ecs:us-west-2:123456789101:task-definition/SuperTaskFamily:513',
             'desiredCount': 201, 'pendingCount': 0, 'runningCount': 201,
             'createdAt': datetime.now(), 'updatedAt': datetime.now(), 'launchType': 'EC2'},
            {'id': 'ecs-svc/1234567891012345679', 'status': 'PRIMARY',
             'taskDefinition': 'arn:aws:ecs:us-west-2:123456789101:task-definition/SuperTaskFamily:513',
             'desiredCount': 201, 'pendingCount': 1, 'runningCount': 200,
             'createdAt': datetime.now(), 'updatedAt': datetime.now(), 'launchType': 'EC2'},
        ]
        assert not is_deployed(deployments)


class TestDeployAndWait(TestCase):
    @staticmethod
    def create_ecs_service_with_status(status):
        return EcsService('cluster-testing', status)

    def test_deploy_and_wait_successful_run(self):
        deployment = MagicMock()
        deployment.get_service.side_effect = [
            self.create_ecs_service_with_status({
                'events': [
                    {'message': 'event1', 'createdAt': datetime.now()}
                ],
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 0}
                ]
            }),
            self.create_ecs_service_with_status({
                'events': [
                    {'message': 'event2', 'createdAt': datetime.now()}
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
            'events': [
                {'message': 'event1', 'createdAt': datetime.now()}
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
                    {'message': 'unable to place tasks due to memory', 'createdAt': start_time + timedelta(seconds=1)},
                ],
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 0,
                     'createdAt': start_time - timedelta(seconds=5),
                     'updatedAt': start_time - timedelta(seconds=2)}
                ]
            }),
            self.create_ecs_service_with_status({
                'events': [
                    {'message': 'started tasks', 'createdAt': start_time + timedelta(seconds=2)},
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
                    {'message': 'unable to place tasks due to memory', 'createdAt': start_time + timedelta(seconds=1)},
                ],
                'deployments': [
                    {'status': 'PRIMARY', 'desiredCount': 5, 'runningCount': 0,
                     'createdAt': start_time - timedelta(seconds=5),
                     'updatedAt': start_time - timedelta(seconds=4)}
                ]
            }),
            self.create_ecs_service_with_status({
                'events': [
                    {'message': 'unable to place tasks due to memory', 'createdAt': start_time + timedelta(seconds=2)},
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
    @patch('cloudlift.deployment.deployer.glob')
    @patch('cloudlift.deployment.deployer.ParameterStore')
    def test_successful_build_config_for_one_main_container(self, mock_parameter_store, mock_glob):
        env_name = "staging"
        cloudlift_service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        essential_container_name = "mainServiceContainer"

        mock_store = MagicMock()
        mock_parameter_store.return_value = mock_store
        mock_store.get_existing_config.return_value = ({'PORT': '80', 'LABEL': 'Dummy'}, {})

        mock_glob.return_value = []

        actual_configurations = build_config(
            env_name,
            cloudlift_service_name,
            sample_env_file_path,
            essential_container_name,

        )

        expected_configurations = {
            "mainServiceContainer": [
                ("PORT", "80"),
                ("LABEL", "Dummy")
            ]
        }

        self.assertEqual(expected_configurations, actual_configurations)

    @patch('builtins.open', mock_open(read_data="PORT=1\nLABEL=test\nADDITIONAL_CONFIG=true"))
    @patch('cloudlift.deployment.deployer.glob')
    @patch('cloudlift.deployment.deployer.ParameterStore')
    def test_failure_build_config_for_if_sample_config_has_additional_keys(self, mock_parameter_store, mock_glob):
        env_name = "staging"
        cloudlift_service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        ecs_service_name = "mainService"

        mock_store = MagicMock()
        mock_parameter_store.return_value = mock_store
        mock_store.get_existing_config.return_value = ({'PORT': '80', 'LABEL': 'Dummy'}, {})

        mock_glob.return_value = []

        with pytest.raises(UnrecoverableException) as pytest_wrapped_e:
            build_config(
                env_name,
                cloudlift_service_name,
                sample_env_file_path,
                ecs_service_name,
            )

        assert pytest_wrapped_e.type == UnrecoverableException
        assert str(pytest_wrapped_e.value) == '"There is no config value for the' \
                                              ' keys of container mainService {\'ADDITIONAL_CONFIG\'}"'

    @patch('builtins.open', mock_open(read_data="PORT=1\nLABEL=test"))
    @patch('cloudlift.deployment.deployer.glob')
    @patch('cloudlift.deployment.deployer.ParameterStore')
    def test_failure_build_config_for_if_parameter_store_has_additional_keys(self, mock_parameter_store, mock_glob):
        env_name = "staging"
        cloudlift_service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        ecs_service_name = "mainService"

        mock_store = MagicMock()
        mock_parameter_store.return_value = mock_store
        mock_store.get_existing_config.return_value = ({'PORT': '80', 'LABEL': 'Dummy', 'ADDITIONAL_KEYS': 'true'}, {})

        mock_glob.return_value = []

        with pytest.raises(UnrecoverableException) as pytest_wrapped_e:
            build_config(
                env_name,
                cloudlift_service_name,
                sample_env_file_path,
                ecs_service_name,
            )

        assert pytest_wrapped_e.type == UnrecoverableException
        assert str(pytest_wrapped_e.value) == '"There is no config value for the keys' \
                                              ' in test-env.sample file {\'ADDITIONAL_KEYS\'}"'

    @patch('builtins.open', new_callable=mock_open, read_data="PORT=1\nLABEL=test")
    @patch('cloudlift.deployment.deployer.glob')
    @patch('cloudlift.deployment.deployer.ParameterStore')
    def test_successful_build_config_with_sidecars(self, mock_parameter_store, mock_glob, mo):
        handlers = (mo.return_value, mock_open(read_data="LISTEN_PORT=1234").return_value,)
        mo.side_effect = handlers

        env_name = "staging"
        cloudlift_service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        essential_container_name = "mainServiceContainer"

        mock_store = MagicMock()
        mock_parameter_store.return_value = mock_store
        mock_store.get_existing_config.return_value = (
            {'PORT': '80', 'LABEL': 'Dummy'},
            {'redis': {'LISTEN_PORT': '6379'}},
        )

        mock_glob.return_value = ['sidecar_redis_test-env.sample']

        actual_configurations = build_config(
            env_name,
            cloudlift_service_name,
            sample_env_file_path,
            essential_container_name,
        )

        expected_configurations = {
            "mainServiceContainer": [
                ("PORT", "80"),
                ("LABEL", "Dummy")
            ],
            "redisContainer": [
                ('LISTEN_PORT', '6379')
            ]
        }

        self.assertEqual(expected_configurations, actual_configurations)

    @patch('builtins.open', new_callable=mock_open, read_data="PORT=1\nLABEL=test")
    @patch('cloudlift.deployment.deployer.glob')
    @patch('cloudlift.deployment.deployer.ParameterStore')
    def test_failure_of_build_config_for_sidecars_configs_mismatch(self, mock_parameter_store, mock_glob, mo):
        handlers = (mo.return_value, mock_open(read_data="LISTEN_PORT=1234").return_value,)
        mo.side_effect = handlers

        env_name = "staging"
        cloudlift_service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        ecs_service_name = "mainService"

        mock_store = MagicMock()
        mock_parameter_store.return_value = mock_store
        mock_store.get_existing_config.return_value = (
            {'PORT': '80', 'LABEL': 'Dummy'},
            {'redis': {'LISTEN_PORT': '6379', 'EXTRA_VAR': 'value'}},
        )

        mock_glob.return_value = ['sidecar_redis_test-env.sample']

        with pytest.raises(UnrecoverableException) as pytest_wrapped_e:
            build_config(
                env_name,
                cloudlift_service_name,
                sample_env_file_path,
                ecs_service_name,
            )

        mock_glob.assert_called_with('sidecar_*_test-env.sample')
        assert pytest_wrapped_e.type == UnrecoverableException
        assert str(pytest_wrapped_e.value) == '"There is no config value for the keys in ' \
                                              'sidecar_redis_test-env.sample file {\'EXTRA_VAR\'}"'

    @patch('builtins.open', new_callable=mock_open, read_data="PORT=1\nLABEL=test")
    @patch('cloudlift.deployment.deployer.glob')
    @patch('cloudlift.deployment.deployer.ParameterStore')
    def test_failure_if_sample_for_sidecar_present(self, mock_parameter_store, mock_glob, mo):
        handlers = (mo.return_value, mock_open(read_data="LISTEN_PORT=1234").return_value,)
        mo.side_effect = handlers

        env_name = "staging"
        cloudlift_service_name = "Dummy"
        sample_env_file_path = "test-env.sample"
        ecs_service_name = "mainService"

        mock_store = MagicMock()
        mock_parameter_store.return_value = mock_store
        mock_store.get_existing_config.return_value = (
            {'PORT': '80', 'LABEL': 'Dummy'},
            {'redis': {'LISTEN_PORT': '6379', 'EXTRA_VAR': 'value'}},
        )

        mock_glob.return_value = ['sidecar_redis_test-env.sample', 'sidecar_nginx_test-env.sample']

        with pytest.raises(UnrecoverableException) as pytest_wrapped_e:
            build_config(
                env_name,
                cloudlift_service_name,
                sample_env_file_path,
                ecs_service_name,
            )

        assert pytest_wrapped_e.type == UnrecoverableException
        assert '"There is a mismatch in sidecar configuratons. ' \
            'Env Samples found: [\'sidecar_nginx_test-env.sample\', \'sidecar_redis_test-env.sample\'], ' \
            'Configurations present for: [\'sidecar_redis_test-env.sample\']"' == str(pytest_wrapped_e.value)
