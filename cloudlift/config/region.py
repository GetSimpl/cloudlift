import boto3
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
    return boto3.session.Session(
        region_name=get_region_for_environment(environment)
    ).client(resource)


def get_resource_for(resource, environment):
    return boto3.session.Session(
        region_name=get_region_for_environment(environment)
    ).resource(resource)


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
