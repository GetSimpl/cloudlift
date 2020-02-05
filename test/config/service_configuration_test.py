import boto3
from moto import mock_dynamodb2

from cloudlift.config.service_configuration import ServiceConfiguration
from cloudlift.version import VERSION


class TestServiceConfiguration(object):
    def setup_existing_params(self):
        client = boto3.resource('dynamodb')
        client.create_table(
            TableName='service_configurations',
            AttributeDefinitions=[
                {
                    'AttributeName': 'service_name',
                    'AttributeType': 'S',
                },
                {
                    'AttributeName': 'environment',
                    'AttributeType': 'S',
                }
            ],
            KeySchema=[
                {
                    'AttributeName': 'service_name',
                    'KeyType': 'HASH',
                },
                {
                    'AttributeName': 'environment',
                    'KeyType': 'RANGE',
                }
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 10,
                'WriteCapacityUnits': 10
            }
        )
        table = client.Table('service_configurations')
        table.update_item(
            TableName='service_configurations',
            Key={
                'service_name': 'test-service',
                'environment': 'dummy-staging'
            },
            UpdateExpression='SET configuration = :configuration',
            ExpressionAttributeValues={
                ':configuration': {
                    "cloudlift_version": VERSION,
                    "services": {
                        "TestService": {
                            "memory_reservation": 1000,
                            "command": None,
                            "http_interface": {
                                "internal": True,
                                "container_port": 80,
                                "restrict_access_to": ["0.0.0.0/0"]
                            }
                        }
                    }
                }
            },
            ReturnValues="UPDATED_NEW"
        )

    @mock_dynamodb2
    def test_initialization(self):
        store_object = ServiceConfiguration('test-service', 'dummy-staging')
        assert store_object.environment == 'dummy-staging'
        assert store_object.service_name == 'test-service'
        assert store_object.table is not None

    @mock_dynamodb2
    def test_get_config(self):
        self.setup_existing_params()

        store_object = ServiceConfiguration('test-service', 'dummy-staging')
        response = store_object.get_config()
        assert response == {
                    "services": {
                        "TestService": {
                            "memory_reservation": 1000,
                            "command": None,
                            "http_interface": {
                                "internal": True,
                                "container_port": 80,
                                "restrict_access_to": [u'0.0.0.0/0']
                            }
                        }
                    }
                }

    @mock_dynamodb2
    def test_set_config(self):
        self.setup_existing_params()

        store_object = ServiceConfiguration('test-service', 'dummy-staging')
        get_response = store_object.get_config()

        get_response["services"]["TestService"]["http_interface"]["restrict_access_to"] = [u"123.123.123.123/32"]
        store_object.set_config(get_response)
        update_response = store_object.get_config()

        assert update_response == {
                    "services": {
                        "TestService": {
                            "memory_reservation": 1000,
                            "command": None,
                            "http_interface": {
                                "internal": True,
                                "container_port": 80,
                                "restrict_access_to": [u"123.123.123.123/32"]
                            }
                        }
                    }
                }
