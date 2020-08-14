from _datetime import datetime
from unittest import TestCase
from unittest.mock import patch, MagicMock, sentinel

from cloudlift.deployment.deployer import is_deployed, create_deployment_timeout_alarm


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


@patch('cloudlift.deployment.deployer.datetime')
@patch('cloudlift.deployment.deployer.boto3')
def test_create_deployment_timeout_alarm(boto3, dt):
    boto3.client = MagicMock()
    boto3.client.put_metric_data = MagicMock()
    cluster_name = sentinel.cluster_name
    service_name = sentinel.service_name
    now = datetime.now()
    dt.utcnow = MagicMock(return_value=now)
    create_deployment_timeout_alarm(cluster_name, service_name)
    boto3.client.assert_called_with('cloudwatch')
    boto3.client.return_value.put_metric_data.assert_called_with(
        Namespace='ECS/DeploymentMetrics',
        MetricData=[
            {
                "MetricName": 'TimedOutCloudliftDeployments',
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
