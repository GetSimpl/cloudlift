from boto3 import client


def get_account_id(sts_client=None):
    sts_client = sts_client or client('sts')
    return sts_client.get_caller_identity().get('Account')
