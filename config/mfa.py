import os

import botocore
from boto3 import client
from boto3.session import Session

from config.account import get_account_id
from deployment.logging import log_bold, log_err


def do_mfa_login(mfa_code=None, region='ap-south-1'):
    username = get_username()
    if not mfa_code:
        mfa_code = input("MFA Code: ")
    mfa_arn = "arn:aws:iam::%s:mfa/%s" % (get_account_id(), username)

    log_bold("Using credentials for " + username)
    try:
        session_params = client('sts').get_session_token(
            DurationSeconds=900,
            SerialNumber=mfa_arn,
            TokenCode=str(mfa_code)
        )
        credentials = session_params['Credentials']
        os.environ['AWS_ACCESS_KEY_ID'] = credentials['AccessKeyId']
        os.environ['AWS_SECRET_ACCESS_KEY'] = credentials['SecretAccessKey']
        os.environ['AWS_SESSION_TOKEN'] = credentials['SessionToken']
        os.environ['AWS_DEFAULT_REGION'] = region
        return session_params
    except botocore.exceptions.ClientError as client_error:
        log_err(str(client_error))
        exit(1)


def get_mfa_session(mfa_code=None, region='ap-south-1'):
    username = get_username()
    if not mfa_code:
        mfa_code = input("MFA Code: ")
    mfa_arn = "arn:aws:iam::%s:mfa/%s" % (get_account_id(), username)

    log_bold("Using credentials for " + username)
    try:
        session_params = client('sts').get_session_token(
            DurationSeconds=900,
            SerialNumber=mfa_arn,
            TokenCode=str(mfa_code)
        )
        credentials = session_params['Credentials']
        return Session(
                aws_access_key_id=credentials['AccessKeyId'],
                aws_secret_access_key=credentials['SecretAccessKey'],
                aws_session_token=credentials['SessionToken'],
                region_name=region
        )
    except botocore.exceptions.ClientError as client_error:
        log_err(str(client_error))
        exit(1)


def get_username():
    return client('sts').get_caller_identity()['Arn'].split("user/")[1]
