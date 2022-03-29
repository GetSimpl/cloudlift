import boto3
from time import sleep
from cloudlift.config.logging import log_bold, log_warning, log


class DynamodbConfiguration:
    """
        Handles configuration in DynamoDB for cloudlift
    """

    def __init__(self, table_name, kv_pairs):
        session = boto3.session.Session()
        self.dynamodb = session.resource('dynamodb')
        self.dynamodb_client = session.client('dynamodb')
        self.kv_pairs = kv_pairs
        self.table_name = table_name

    def _get_table(self):
        table_names = self.dynamodb_client.list_tables()['TableNames']
        if self.table_name not in table_names:
            log_warning("Could not find {} table, creating one..".format(self.table_name))
            self._create_configuration_table()
            self._table_status()
        return self.dynamodb.Table(self.table_name)

    def _create_configuration_table(self):
        key_schema = [
            {'AttributeName': self.kv_pairs[0][0], 'KeyType': 'HASH'}]
        key_schema.extend([{'AttributeName': key, 'KeyType': 'RANGE'}
                            for key, _ in self.kv_pairs[1:]])
        self.dynamodb.create_table(
            TableName=self.table_name,
            KeySchema=key_schema,
            AttributeDefinitions=[
                {'AttributeName': key, 'AttributeType': 'S'} for key, _ in self.kv_pairs],
            BillingMode='PAY_PER_REQUEST'
        )
        log_bold("{} table created!".format(self.table_name))

    def _table_status(self):
        status = ""
        while status == "ACTIVE":
            log("Checking {} table status...".format(self.table_name))
            sleep(1)
            status = self.dynamodb_client.describe_table(
                TableName=self.table_name)["Table"]["TableStatus"]
        sleep(10)
        log("{} table status is ACTIVE".format(self.table_name))
