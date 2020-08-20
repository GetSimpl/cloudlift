from _datetime import datetime, timedelta
from dateutil.tz.tz import tzlocal
from unittest import TestCase
from unittest.mock import patch, MagicMock, sentinel
from cloudlift.deployment.deployer import is_deployed, \
    record_deployment_failure_metric, deploy_and_wait
from cloudlift.deployment.ecs import EcsService, EcsTaskDefinition


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
        timeout_seconds = 4

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
