from boto3 import client


def get_account_id(sts_client=None):
    sts_client = sts_client or client('sts')
    return sts_client.get_caller_identity().get('Account')

def get_user_id(sts_client=None):
    sts_client = sts_client or client('sts')
    username = ""
    account = sts_client.get_caller_identity().get('Account')
    user_id = (sts_client.get_caller_identity()['Arn'].split("/")[0]).split(":")[-1]
    if user_id == "user":
        username = sts_client.get_caller_identity().get('Arn').split('/')[1]
    elif user_id == "assumed-role":
        username = sts_client.get_caller_identity().get('Arn').split('assumed-role/')[1]
    return username, account