from boto3 import client


def get_account_id(sts_client=None):
    sts_client = sts_client or client('sts')
    return sts_client.get_caller_identity().get('Account')

def get_user_id(sts_client=None):
    sts_client = sts_client or client('sts')
    response = client('iam').list_account_aliases()
    return sts_client.get_caller_identity().get('Arn').split('/')[1], response['AccountAliases'][0]
