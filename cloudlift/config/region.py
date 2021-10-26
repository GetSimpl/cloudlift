import boto3
from botocore.config import Config
from cloudlift.exceptions import UnrecoverableException
from cloudlift.config import EnvironmentConfiguration


local_cache = {}


def get_region_for_environment(environment):
    global local_cache
    if 'region' not in local_cache:
        if environment:
            local_cache['region'] = EnvironmentConfiguration(environment).get_config()[environment]['region']
        else:
            # Get the region from the AWS credentials used to execute cloudlift
            aws_session = boto3.session.Session()
            local_cache['region'] = aws_session.region_name

    return local_cache['region']


def get_environment_level_alb_listener(environment):
    env_spec = EnvironmentConfiguration(environment).get_config()[environment]
    if 'loadbalancer_listener_arn' not in env_spec:
        raise UnrecoverableException('environment level ALB not defined. ' +
                                     'Please run update_environment and set "loadbalancer_listener_arn".')

    return env_spec['loadbalancer_listener_arn']


def get_service_templates_bucket_for_environment(environment):
    global local_cache

    if 'bucket' not in local_cache:
        config = EnvironmentConfiguration(environment).get_config()

        if 'service_templates_bucket' not in config[environment]:
            return None

        local_cache['bucket'] = config[environment]['service_templates_bucket']

    return local_cache['bucket']


def get_client_for(resource, environment):
    config = Config(retries=dict(
        max_attempts=100,
        mode='standard',
    ))
    return boto3.session.Session(
        region_name=get_region_for_environment(environment)
    ).client(resource, config=config)


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
