import os

import botocore
from boto3 import client
from boto3.session import Session
from cloudlift.exceptions import UnrecoverableException
from click import prompt
from cloudlift.config import get_account_id
from cloudlift.config.logging import log_bold, log_err, log


def do_mfa_login(mfa_code=None, region='ap-south-1'):
    username = get_username()
    mfa_arn = get_mfa_arn(username)
    if not mfa_code:
        mfa_code = input("MFA Code: ")
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
        raise UnrecoverableException(str(client_error))


def get_mfa_session(mfa_code=None, region='ap-south-1'):
    username = get_username()
    mfa_arn = get_mfa_arn(username)
    if not mfa_code:
        mfa_code = input("MFA Code: ")
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
        raise UnrecoverableException(str(client_error))


def get_username():
    return client('sts').get_caller_identity()['Arn'].split("user/")[1]

def get_mfa_arn(username):
    try:
        response = client('iam').list_mfa_devices(UserName=username)
        if len(response['MFADevices']) == 1:
            return response['MFADevices'][0]['SerialNumber']
        elif len(response['MFADevices']) > 1:
            log_bold("More than one MFA device found \nPlease enter the serial number of the MFA device you want to use")
            for index, device in enumerate(response['MFADevices']):
                log(str(index) + ". " + device["SerialNumber"].split("/")[1])
            n = prompt("serial number", default=0)
            return  response['MFADevices'][n]['SerialNumber']
    except botocore.exceptions.ClientError as client_error:
        raise UnrecoverableException(str(client_error))
