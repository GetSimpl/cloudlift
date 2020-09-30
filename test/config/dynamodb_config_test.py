import unittest
from cloudlift.config.dynamodb_config import DynamodbConfig
from moto import mock_dynamodb2
import boto3
from decimal import Decimal
from mock import patch


DUMMY_CONFIG = {
    "cloudlift_version": 'test-version',
    "notifications_arn": "some",
    "services": {
        "FreeradiusServer": {
            "command": None,
            "memory_reservation": Decimal(1024),
            "secrets_name": "dummy-udp-config",
            "udp_interface": {
                "container_port": Decimal(1812),
                "eip_allocaltion_id1": "eipalloc-02abb9e5e123492ee",
                "eip_allocaltion_id2": "eipalloc-02abb9e5e123492ee",
                "health_check_port": Decimal(1814),
                "internal": False,
                "nlb_enabled": True,
                "restrict_access_to": [
                    "0.0.0.0/0"
                ]
            }
        }
    }
}


class ConfigClassWithFailingValidate(DynamodbConfig):
    def _validate_changes(self, config):
        raise KeyError


class ConfigClassWithPassingValidate(DynamodbConfig):
    def _validate_changes(self, config):
        pass


class TestDynamodbConfig(unittest.TestCase):

    @mock_dynamodb2
    def test_set_and_get_config_in_db(self):
        dynamodb_config_setter = DynamodbConfig('test_dynamodb_config',
                                                [('key1', 'valuexyz'), ('key2', 'valueabc')])
        dynamodb_config_setter.set_config_in_db(DUMMY_CONFIG)
        dynamodb_config_getter = DynamodbConfig('test_dynamodb_config',
                                                [('key1', 'valuexyz'), ('key2', 'valueabc')])
        fetched_config = dynamodb_config_getter.get_config_in_db()
        self.assertDictEqual(fetched_config, DUMMY_CONFIG)

    @mock_dynamodb2
    def test_validate(self):
        config_setter_with_passing_validate = ConfigClassWithPassingValidate('test_cloudlift_dynamodb_config',
                                                                             [('key1', 'valuexyz'), ('key2', 'valueabc')])
        config_setter_with_failing_validate = ConfigClassWithFailingValidate('test_cloudlift_dynamodb_config',
                                                                             [('key1', 'valuexyz'), ('key2', 'valueabc')])
        config_setter_with_passing_validate.set_config_in_db(DUMMY_CONFIG)

        self.assertRaises(KeyError, config_setter_with_failing_validate.set_config_in_db, DUMMY_CONFIG)

    @mock_dynamodb2
    def test_create_configuration_table(self):
        DynamodbConfig('creation_test_table', [('key1', 'valuexyz'), ('key2', 'valueabc'), ('random_key', '12345')])
        dynamodb_resource = boto3.session.Session().resource('dynamodb')
        created_table = dynamodb_resource.Table('creation_test_table')
        assert created_table.key_schema == [{'AttributeName': 'key1', 'KeyType': 'HASH'}, {'AttributeName': 'key2', 'KeyType': 'RANGE'}, {'AttributeName': 'random_key', 'KeyType': 'RANGE'}]
        assert created_table.attribute_definitions == [{'AttributeName': 'key1', 'AttributeType': 'S'}, {'AttributeName': 'key2', 'AttributeType': 'S'}, {'AttributeName': 'random_key', 'AttributeType': 'S'}]
        assert created_table.table_status == 'ACTIVE'

    @mock_dynamodb2
    @patch('cloudlift.config.dynamodb_config.DynamodbConfig._create_configuration_table')
    def test_get_table(self, mock_create_conf_table):
        dynamodb_config = DynamodbConfig('test_table', [('primary_attr', 'v1'), ('secondary_attr', 'v2')])
        assert mock_create_conf_table.call_count == 1
        dynamodb_resource = boto3.session.Session().resource('dynamodb')
        dynamodb_resource.create_table(
            TableName='test_table',
            KeySchema=[{'AttributeName': 'primary_attr', 'KeyType': 'HASH'},
                       {'AttributeName': 'secondary_attr', 'KeyType': 'RANGE'}],
            AttributeDefinitions=[{'AttributeName': 'primary_attr', 'AttributeType': 'S'},
                                  {'AttributeName': 'secondary_attr', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST'
        )
        fetched_table = dynamodb_config._get_table()
        assert fetched_table.table_status == 'ACTIVE'
        assert fetched_table.key_schema == [{'AttributeName': 'primary_attr', 'KeyType': 'HASH'}, {'AttributeName': 'secondary_attr', 'KeyType': 'RANGE'}]
        assert fetched_table.attribute_definitions == [{'AttributeName': 'primary_attr', 'AttributeType': 'S'}, {'AttributeName': 'secondary_attr', 'AttributeType': 'S'}]
