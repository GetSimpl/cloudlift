import boto3
from botocore.exceptions import ClientError
from cloudlift.exceptions import UnrecoverableException

from cloudlift.config import EnvironmentConfiguration
from cloudlift.config.logging import log_err

def get_region_for_environment(environment):
    if environment:
        return EnvironmentConfiguration(environment).get_config()[environment]['region']
    else:
        # Get the region from the AWS credentials used to execute cloudlift
        aws_session = boto3.session.Session()
        return aws_session.region_name


def get_client_for(resource, environment):
    try:
        return boto3.session.Session(
            region_name=get_region_for_environment(environment)
        ).client(resource)
    except ClientError as error:
        if error.response['Error']['Code'] == 'ExpiredTokenException':
            raise UnrecoverableException("AWS session associated with this profile has expired or is otherwise invalid")
        elif error.response['Error']['Code'] == 'InvalidIdentityTokenException':
            raise UnrecoverableException("AWS token that was passed could not be validated by Amazon Web Services")
        elif error.response['Error']['Code'] == 'RegionDisabledException':
            raise UnrecoverableException("STS is not activated in the requested region for the account that is being asked to generate credentials")
        elif error.response['Error']['Code'] == 'AccessDeniedException':
            raise UnrecoverableException("User is not authorized to perform get boto3 client session on %s" % resource)
        else:
            raise UnrecoverableException("Unable to find valid AWS credentials")

def get_resource_for(resource, environment):
    try:
        return boto3.session.Session(
            region_name=get_region_for_environment(environment)
        ).resource(resource)
    except ClientError as error:
        if error.response['Error']['Code'] == 'ExpiredTokenException':
            raise UnrecoverableException(
                "AWS session associated with this profile has expired or is otherwise invalid")
        elif error.response['Error']['Code'] == 'InvalidIdentityTokenException':
            raise UnrecoverableException(
                "AWS token that was passed could not be validated by Amazon Web Services")
        elif error.response['Error']['Code'] == 'RegionDisabledException':
            raise UnrecoverableException(
                "STS is not activated in the requested region for the account that is being asked to generate credentials")
        elif error.response['Error']['Code'] == 'AccessDeniedException':
            raise UnrecoverableException("User is not authorized to perform get boto3 resource session on %s" % resource)
        else:
            raise UnrecoverableException(
                "Unable to find valid AWS credentials")


def get_notifications_arn_for_environment(environment):
    try:
        return EnvironmentConfiguration(
            environment
        ).get_config()[environment]['environment']["notifications_arn"]
    except KeyError:
        raise UnrecoverableException("Unable to find notifications arn for {environment}".format(**locals()))


def get_ssl_certification_for_environment(environment):
    try:
        return EnvironmentConfiguration(
            environment
        ).get_config()[environment]['environment']["ssl_certificate_arn"]
    except KeyError:
        raise UnrecoverableException("Unable to find ssl certificate for {environment}".format(**locals()))
