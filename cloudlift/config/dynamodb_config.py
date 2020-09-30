import boto3
from botocore.exceptions import ClientError
from cloudlift.version import VERSION
from cloudlift.exceptions import UnrecoverableException
from cloudlift.config.logging import log_bold, log_err, log_warning


class DynamodbConfig:
    """
        Handles configuration in DynamoDB for cloudlift
    """
    def __init__(self, table_name, kv_pairs):
        session = boto3.session.Session()
        self.dynamodb = session.resource('dynamodb')
        self.kv_pairs = kv_pairs
        self.table_name = table_name
        self.table = self._get_table()

    def get_config_in_db(self):
        '''
            Get configuration from DynamoDB
        '''
        try:
            configuration_response = self.table.get_item(
                Key={k: v for k, v in self.kv_pairs},
                ConsistentRead=True,
                AttributesToGet=[
                    'configuration'
                ]
            )
            if 'Item' in configuration_response:
                return configuration_response['Item']['configuration']
            return None
        except ClientError:
            raise UnrecoverableException("Unable to fetch configuration from DynamoDB.")

    def set_config_in_db(self, config):
        '''
            Set configuration in DynamoDB
        '''
        self._validate_changes(config)
        try:
            configuration_response = self.table.update_item(
                TableName=self.table_name,
                Key={k: v for k, v in self.kv_pairs},
                UpdateExpression='SET configuration = :configuration',
                ExpressionAttributeValues={
                    ':configuration': config
                },
                ReturnValues="UPDATED_NEW"
            )
            return configuration_response
        except ClientError:
            raise UnrecoverableException("Unable to store service configuration in DynamoDB.")

    def _get_table(self):
        dynamodb_client = boto3.session.Session().client('dynamodb')
        table_names = dynamodb_client.list_tables()['TableNames']
        if self.table_name not in table_names:
            log_warning("Could not find configuration table, creating one..")
            self._create_configuration_table()
        return self.dynamodb.Table(self.table_name)

    def _create_configuration_table(self):
        key_schema = [{'AttributeName': self.kv_pairs[0][0], 'KeyType': 'HASH'}]
        key_schema.extend([{'AttributeName': key, 'KeyType': 'RANGE'} for key, _ in self.kv_pairs[1:]])
        self.dynamodb.create_table(
            TableName=self.table_name,
            KeySchema=key_schema,
            AttributeDefinitions=[{'AttributeName': key, 'AttributeType': 'S'} for key, _ in self.kv_pairs],
            BillingMode='PAY_PER_REQUEST'
        )
        log_bold("{} table created!".format(self.table_name))

    def _validate_changes(self, config):
        pass
