import boto3
import pytest
from moto import mock_dynamodb2, mock_ssm

from cloudlift.config import ParameterStore


class TestParameterStore(object):
    def setup_environment_config(self):
        client = boto3.resource('dynamodb')
        client.create_table(
            TableName='environment_configurations',
            AttributeDefinitions=[
                {
                    'AttributeName': 'environment',
                    'AttributeType': 'S',
                }
            ],
            KeySchema=[
                {
                    'AttributeName': 'environment',
                    'KeyType': 'HASH',
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 10,
                'WriteCapacityUnits': 10
            }
        )
        table = client.Table('environment_configurations')
        table.update_item(
            TableName='environment_configurations',
            Key={
                'environment': 'dummy-staging'
            },
            UpdateExpression='SET configuration = :configuration',
            ExpressionAttributeValues={
                ':configuration': {
                    "staging": {
                        "cluster": {
                            "instance_type": "m5.xlarge",
                            "key_name": "staging-cluster-v3",
                            "max_instances": 10,
                            "min_instances": 5
                        },
                        "environment": {
                            "notifications_arn": "arn:aws:sns:ap-south-1:725827686899:non-prod-mumbai",
                            "ssl_certificate_arn": "arn:aws:acm:ap-south-1:725827686899:certificate/380232d3-d868-4ce3-a43d-211cdfd39d26"
                        },
                        "region": "ap-south-1",
                        "vpc": {
                            "cidr": "10.30.0.0/16",
                            "nat-gateway": {
                                "elastic-ip-allocation-id": "eipalloc-05f2599c8bd8d3d28"
                            },
                            "subnets": {
                                "private": {
                                    "subnet-1": {
                                        "cidr": "10.30.4.0/22"
                                    },
                                    "subnet-2": {
                                        "cidr": "10.30.12.0/22"
                                    }
                                },
                                "public": {
                                    "subnet-1": {
                                        "cidr": "10.30.0.0/22"
                                    },
                                    "subnet-2": {
                                        "cidr": "10.30.8.0/22"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            ReturnValues="UPDATED_NEW"
        )

    def setup_existing_params(self):
        client = boto3.client('ssm')
        for i in range(14):
            client.put_parameter(Name="/dummy-staging/test-service/DUMMY_VAR"+str(i), Value="dummy_values_"+str(i), Type="SecureString", KeyId='alias/aws/ssm', Overwrite=False)

    @mock_dynamodb2
    def test_initialization(self):
        store_object = ParameterStore('test-service', 'dummy-staging')
        assert store_object.environment == 'dummy-staging'
        assert store_object.service_name == 'test-service'
        assert store_object.path_prefix == '/dummy-staging/test-service/'

    @mock_ssm
    @mock_dynamodb2
    def test_get_existing_config(self):
        self.setup_existing_params()

        store_object = ParameterStore('test-service', 'dummy-staging')
        response = store_object.get_existing_config()
        assert response == {u'DUMMY_VAR12': u'dummy_values_12', u'DUMMY_VAR13': u'dummy_values_13', u'DUMMY_VAR10': u'dummy_values_10', u'DUMMY_VAR11': u'dummy_values_11', u'DUMMY_VAR8': u'dummy_values_8', u'DUMMY_VAR9': u'dummy_values_9', u'DUMMY_VAR0': u'dummy_values_0', u'DUMMY_VAR1': u'dummy_values_1', u'DUMMY_VAR2': u'dummy_values_2', u'DUMMY_VAR3': u'dummy_values_3', u'DUMMY_VAR4': u'dummy_values_4', u'DUMMY_VAR5': u'dummy_values_5', u'DUMMY_VAR6': u'dummy_values_6', u'DUMMY_VAR7': u'dummy_values_7'}

    @mock_ssm
    @mock_dynamodb2
    def test_get_existing_config_as_string(self):
        self.setup_existing_params()

        store_object = ParameterStore('test-service', 'dummy-staging')
        response = store_object.get_existing_config_as_string()
        assert response == 'DUMMY_VAR0=dummy_values_0\nDUMMY_VAR1=dummy_values_1\nDUMMY_VAR10=dummy_values_10\nDUMMY_VAR11=dummy_values_11\nDUMMY_VAR12=dummy_values_12\nDUMMY_VAR13=dummy_values_13\nDUMMY_VAR2=dummy_values_2\nDUMMY_VAR3=dummy_values_3\nDUMMY_VAR4=dummy_values_4\nDUMMY_VAR5=dummy_values_5\nDUMMY_VAR6=dummy_values_6\nDUMMY_VAR7=dummy_values_7\nDUMMY_VAR8=dummy_values_8\nDUMMY_VAR9=dummy_values_9'

    @mock_ssm
    @mock_dynamodb2
    def test_set_config(self):
        self.setup_existing_params()

        differences = [
            ['change', 'DUMMY_VAR12', ('dummy_values_12', 'test_change')],
            ['add', '', [('DUMMY_VAR20', 'test_add_20'), ('DUMMY_VAR21', 'test_add_21')]],
            ['remove', '', [('DUMMY_VAR13', 'dummy_values_13'), ('DUMMY_VAR10', 'dummy_values_10')]]
        ]
        store_object = ParameterStore('test-service', 'dummy-staging')
        store_object.set_config(differences)
        response = store_object.get_existing_config()
        assert response == {u'DUMMY_VAR12': u'test_change', u'DUMMY_VAR11': u'dummy_values_11', u'DUMMY_VAR8': u'dummy_values_8', u'DUMMY_VAR9': u'dummy_values_9', u'DUMMY_VAR0': u'dummy_values_0', u'DUMMY_VAR1': u'dummy_values_1', u'DUMMY_VAR2': u'dummy_values_2', u'DUMMY_VAR3': u'dummy_values_3', u'DUMMY_VAR4': u'dummy_values_4', u'DUMMY_VAR5': u'dummy_values_5', u'DUMMY_VAR6': u'dummy_values_6', u'DUMMY_VAR7': u'dummy_values_7', u'DUMMY_VAR20': u'test_add_20', u'DUMMY_VAR21': u'test_add_21'}

    @mock_ssm
    @mock_dynamodb2
    def test_set_config_validation(self, capsys):
        self.setup_environment_config()
        self.setup_existing_params()

        invalid_differences = [
            ['change', 'DUMMY_VAR12', ('dummy_values_12', '')],
            ['add', '', [('DUMMY_VAR22', ''),('DUMMY_VAR*', 'valid_value')]]
        ]
        store_object = ParameterStore('test-service', 'dummy-staging')
        with pytest.raises(SystemExit) as pytest_wrapped_e:
            store_object.set_config(invalid_differences)
        captured = capsys.readouterr()
        assert captured.out == "'' is not a valid value for key 'DUMMY_VAR12'\n'' is not a valid value for key 'DUMMY_VAR22'\n'DUMMY_VAR*' is not a valid key.\n"
        assert pytest_wrapped_e.type == SystemExit
        assert pytest_wrapped_e.value.code == 1
        response = store_object.get_existing_config()
        assert response == {u'DUMMY_VAR12': u'dummy_values_12', u'DUMMY_VAR11': u'dummy_values_11', u'DUMMY_VAR8': u'dummy_values_8', u'DUMMY_VAR9': u'dummy_values_9', u'DUMMY_VAR0': u'dummy_values_0', u'DUMMY_VAR1': u'dummy_values_1', u'DUMMY_VAR2': u'dummy_values_2', u'DUMMY_VAR3': u'dummy_values_3', u'DUMMY_VAR4': u'dummy_values_4', u'DUMMY_VAR5': u'dummy_values_5', u'DUMMY_VAR6': u'dummy_values_6', u'DUMMY_VAR7': u'dummy_values_7', u'DUMMY_VAR13': u'dummy_values_13', u'DUMMY_VAR10': u'dummy_values_10'}
