from unittest import TestCase
from unittest.mock import patch

import boto3
from moto import mock_dynamodb2

from cloudlift.config import ServiceConfiguration
from cloudlift.exceptions import UnrecoverableException
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
                    'ecr_repo': {'name': 'test-service-repo'},
                    "services": {
                        "TestService": {
                            "memory_reservation": 1000,
                            "secrets_name": "secret-config",
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
            'ecr_repo': {'name': 'test-service-repo'},
            "services": {
                "TestService": {
                    "memory_reservation": 1000,
                    'secrets_name': 'secret-config',
                    "command": None,
                    "http_interface": {
                        "internal": True,
                        "container_port": 80,
                        "restrict_access_to": [u'0.0.0.0/0'],
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
            'ecr_repo': {'name': 'test-service-repo'},
            "services": {
                "TestService": {
                    "memory_reservation": 1000,
                    'secrets_name': 'secret-config',
                    "command": None,
                    "http_interface": {
                        "internal": True,
                        "container_port": 80,
                        "restrict_access_to": [u"123.123.123.123/32"],
                    }
                }
            }
        }

    @mock_dynamodb2
    def test_set_config_stop_timeout(self):
        self.setup_existing_params()

        store_object = ServiceConfiguration('test-service', 'dummy-staging')
        get_response = store_object.get_config()

        get_response["services"]["TestService"]["stop_timeout"] = 120
        store_object.set_config(get_response)
        update_response = store_object.get_config()

        assert update_response == {
            "ecr_repo": {"name": "test-service-repo"},
            "services": {
                "TestService": {
                    "memory_reservation": 1000,
                    'secrets_name': 'secret-config',
                    "command": None,
                    "http_interface": {
                        "internal": True,
                        "container_port": 80,
                        "restrict_access_to": [u'0.0.0.0/0'],
                    },
                    "stop_timeout": 120
                }
            }
        }


class TestServiceConfigurationValidation(TestCase):
    @mock_dynamodb2
    @patch("cloudlift.config.service_configuration.getcwd")
    def test_default_service_configuration_ecr_repo(self, getcwd):
        getcwd.return_value = "/path/to/dummy"

        service = ServiceConfiguration('test-service', 'test')
        conf = service._default_service_configuration()

        self.assertEqual({'name': 'dummy-repo'}, conf.get('ecr_repo'))

    @mock_dynamodb2
    def test_set_config_placement_constraints(self):
        service = ServiceConfiguration('test-service', 'test')

        try:
            service._validate_changes({
                'cloudlift_version': 'test',
                'ecr_repo': {'name': 'test-service-repo'},
                'services': {
                    'TestService': {
                        'memory_reservation': 1000,
                        'secrets_name': 'secret-config',
                        'command': None,
                        'placement_constraints': [
                            {
                                'type': 'memberOf',
                                'expression': 'expr'
                            }
                        ]
                    }
                }
            })
        except UnrecoverableException as e:
            self.fail('Exception thrown: {}'.format(e))

        try:
            service._validate_changes({
                'cloudlift_version': 'test',
                'ecr_repo': {'name': 'test-service-repo'},
                'services': {
                    'TestService': {
                        'memory_reservation': 1000,
                        'secrets_name': 'secret-config',
                        'command': None,
                        'placement_constraints': [{
                            'type': 'invalid'
                        }]
                    }
                }
            })
            self.fail('Validation error expected but validation passed')
        except UnrecoverableException as e:
            self.assertTrue("'invalid' is not one of ['memberOf', 'distinctInstance']" in str(e))

    @mock_dynamodb2
    def test_set_config_system_controls(self):
        service = ServiceConfiguration('test-service', 'test')

        try:
            service._validate_changes({
                'cloudlift_version': 'test',
                'ecr_repo': {'name': 'test-service-repo'},
                'services': {
                    'TestService': {
                        'memory_reservation': 1000,
                        'command': None,
                        'secrets_name': 'secret-config',
                        'system_controls': [
                            {
                                'namespace': 'ns',
                                'value': 'val'
                            }
                        ]
                    }
                }
            })
        except UnrecoverableException as e:
            self.fail('Exception thrown: {}'.format(e))

        try:
            service._validate_changes({
                'cloudlift_version': 'test',
                'ecr_repo': {'name': 'test-service-repo'},
                'services': {
                    'TestService': {
                        'memory_reservation': 1000,
                        'command': None,
                        'secrets_name': 'secret-config',
                        'system_controls': "invalid"
                    }
                }
            })
            self.fail('Validation error expected but validation passed')
        except UnrecoverableException as e:
            self.assertTrue("'invalid' is not of type 'array'" in str(e))

    @mock_dynamodb2
    def test_set_config_http_interface(self):
        service = ServiceConfiguration('test-service', 'test')

        try:
            service._validate_changes({
                'cloudlift_version': 'test',
                'ecr_repo': {'name': 'test-service-repo'},
                'services': {
                    'TestService': {
                        'memory_reservation': 1000,
                        'command': None,
                        'secrets_name': 'secret-config',
                        'http_interface': {
                            'internal': True,
                            'container_port': 8080,
                            'restrict_access_to': ['0.0.0.0/0'],
                        }
                    }
                }
            })
        except UnrecoverableException as e:
            self.fail('Exception thrown: {}'.format(e))

    @mock_dynamodb2
    def test_set_config_health_check_command(self):
        service = ServiceConfiguration('test-service', 'test')

        try:
            service._validate_changes({
                'cloudlift_version': 'test',
                'ecr_repo': {'name': 'test-service-repo'},
                'services': {
                    'TestService': {
                        'memory_reservation': 1000,
                        'command': None,
                        'secrets_name': 'secret-config',
                        'http_interface': {
                            'internal': True,
                            'container_port': 8080,
                            'restrict_access_to': ['0.0.0.0/0'],
                        },
                        "container_health_check": {
                            "command": "echo 'Working'",
                            "start_period": 30,
                            "retries": 4,
                            "interval": 5,
                            "timeout": 30,
                        }
                    }
                }
            })
        except UnrecoverableException as e:
            self.fail('Exception thrown: {}'.format(e))

        try:
            service._validate_changes({
                'cloudlift_version': 'test',
                'ecr_repo': {'name': 'test-service-repo'},
                'services': {
                    'TestService': {
                        'memory_reservation': 1000,
                        'command': None,
                        'secrets_name': 'secret-config',
                        'http_interface': {
                            'internal': True,
                            'container_port': 8080,
                            'restrict_access_to': ['0.0.0.0/0'],
                        },
                        "container_health_check": {
                            "start_period": 123,
                        }
                    }
                }
            })
            self.fail('Exception expected but did not fail')
        except UnrecoverableException as e:
            self.assertTrue(True)

    @mock_dynamodb2
    def test_sidecars(self):
        service = ServiceConfiguration('test-service', 'test')

        try:
            service._validate_changes({
                'cloudlift_version': 'test',
                'ecr_repo': {'name': 'test-service-repo'},
                'services': {
                    'TestService': {
                        'memory_reservation': 1000,
                        'command': None,
                        'secrets_name': 'secret-config',
                        'sidecars': [
                            {
                                'name': 'redis',
                                'image': 'redis:latest',
                                'memory_reservation': 128
                            },
                            {
                                'name': 'envoy',
                                'image': 'envoy:latest',
                                'memory_reservation': 256,
                                'command': ['./start']
                            }
                        ]
                    }
                }
            })
        except UnrecoverableException as e:
            self.fail('Exception thrown: {}'.format(e))
