import datetime
import unittest

from cloudlift.deployment.service_information_fetcher import ServiceInformationFetcher
from dateutil.tz import tzutc
from mock import patch, MagicMock

service = "dummy"
env = "test"


class TestServiceInformationFetcher(unittest.TestCase):

    @patch('cloudlift.deployment.service_information_fetcher.get_client_for')
    def test_fetch_service_cfn_info(self, mock_get_client_for):
        mock_cfn_client = MagicMock()
        mock_get_client_for.return_value = mock_cfn_client
        mock_cfn_client.describe_stacks.return_value = _describe_stacks_output()

        sif = ServiceInformationFetcher(service, env)

        expected_service_info = {
            'ServiceTwo': {'ecs_service_name': 'dummy-sen-test-ServiceTwo-45E0C5QX2HUV', 'secrets_name_prefix': None},
            'ServiceOne': {'ecs_service_name': 'dummy-sen-test-ServiceOne-X9NCSHOSMM5S',
                           'secrets_name_prefix': 'dummy'}}
        self.assertDictEqual(expected_service_info, sif.service_info)
        mock_cfn_client.describe_stacks.assert_called_once_with(StackName='dummy-test')


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
            {'OutputKey': 'ServiceOneSecretsNamePrefix', 'OutputValue': 'dummy',
             'Description': 'AWS secrets manager name prefix to pull the secrets from'},
            {'OutputKey': 'ServiceTwoEcsServiceName', 'OutputValue': 'dummy-sen-test-ServiceTwo-45E0C5QX2HUV',
             'Description': 'The ECS name which needs to be entered'}, {'OutputKey': 'CloudliftOptions',
                                                                        'OutputValue': '{"services": {"ServiceTwo": {"system_controls": [], "memory_reservation": 700, "command": null, "http_interface": {"restrict_access_to": ["0.0.0.0/0"], "container_port": 80, "internal": false, "health_check_path": "/elb-check", "alb": {"create_new": true}}}, "ServiceOne": {"system_controls": [], "memory_reservation": 700, "command": null, "http_interface": {"restrict_access_to": ["0.0.0.0/0"], "container_port": 80, "internal": false, "health_check_path": "/elb-check", "alb": {"create_new": true}}, "secrets_name_prefix": "dummy"}}}',
                                                                        'Description': 'Options used with cloudlift when building this service'},
            {'OutputKey': 'ServiceTwoURL',
             'OutputValue': 'https://ServiceTwoTest-707380103.us-west-2.elb.amazonaws.com',
             'Description': 'The URL at which the service is accessible'},
            {'OutputKey': 'StackName', 'OutputValue': 'dummy-sen-test', 'Description': 'The name of the stack'},
            {'OutputKey': 'ServiceOneEcsServiceName', 'OutputValue': 'dummy-sen-test-ServiceOne-X9NCSHOSMM5S',
             'Description': 'The ECS name which needs to be entered'}, {'OutputKey': 'StackId',
                                                                        'OutputValue': 'arn:aws:cloudformation:us-west-2:408750594584:stack/dummy-sen-test/3eeaa640-edcf-11ea-9f4d-0a3d9b1fa9c6',
                                                                        'Description': 'The unique ID of the stack. To be supplied to circle CI environment variables to validate during deployment.'}],
        'Tags': [], 'EnableTerminationProtection': False,
        'DriftInformation': {'StackDriftStatus': 'NOT_CHECKED'}}]}
