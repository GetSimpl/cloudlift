from _datetime import datetime
from unittest import TestCase

from cloudlift.deployment.deployer import is_deployed


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