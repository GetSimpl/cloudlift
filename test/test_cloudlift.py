import os
from pathlib import Path

import boto3
import requests
import urllib3
from mock import patch

from cloudlift.config import ServiceConfiguration, VERSION
from cloudlift.config import secrets_manager
from cloudlift.deployment.service_creator import ServiceCreator
from cloudlift.deployment.service_updater import ServiceUpdater
from cloudlift.utils import wait_until

TEST_DIR = Path(__file__).resolve().parent
REDIS_IMAGE = os.getenv('CLOUDLIFT_REDIS_IMAGE', 'redis')


def setup_module(module):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


environment_name = 'ci'
service_name = 'cfn-dummy'


def mocked_service_config(cls, *args, **kwargs):
    return {
        "cloudlift_version": VERSION,
        'ecr_repo': {'name': 'dummy-repo'},
        "services": {
            "Dummy": {
                "command": None,
                "secrets_name": f'{service_name}-{environment_name}',
                "sidecars": [
                    {"name": "redis", "image": REDIS_IMAGE, "memory_reservation": 256}
                ],
                "http_interface": {
                    "alb": {
                        "create_new": True,
                        "target_5xx_error_threshold": 10
                    },
                    "container_port": 80,
                    "internal": False,
                    "restrict_access_to": [
                        "0.0.0.0/0"
                    ],
                    "health_check_path": "/elb-check"
                },
                "task_role_attached_managed_policy_arns": ["arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess"],
                "memory_reservation": 512
            }
        }
    }


def mocked_service_with_parameter_store_config(cls, *args, **kwargs):
    return {
        "cloudlift_version": VERSION,
        'ecr_repo': {'name': 'dummy-repo'},
        "services": {
            "Dummy": {
                "command": None,
                "sidecars": [
                    {"name": "redis", "image": REDIS_IMAGE, "memory_reservation": 256}
                ],
                "http_interface": {
                    "alb": {
                        "create_new": True,
                        "target_5xx_error_threshold": 10
                    },
                    "container_port": 80,
                    "internal": False,
                    "restrict_access_to": [
                        "0.0.0.0/0"
                    ],
                    "health_check_path": "/elb-check"
                },
                "task_role_attached_managed_policy_arns": ["arn:aws:iam::aws:policy/AmazonEC2ReadOnlyAccess"],
                "memory_reservation": 512
            }
        }
    }


def test_cloudlift_can_deploy_to_ec2(keep_resources):
    expected_string = 'This is dummy app. Label: Demo. Redis ' \
                      'PING: PONG. AWS EC2 READ ACCESS: True'
    mocked_config = mocked_service_config
    stack_name = f'{service_name}-{environment_name}'
    cfn_client = boto3.client('cloudformation')
    delete_stack(cfn_client, stack_name, wait=True)
    secrets_manager.set_secrets_manager_config(environment_name, stack_name,
                                               {'PORT': '80', 'LABEL': 'Demo'})
    secrets_manager.set_secrets_manager_config(environment_name, f'{stack_name}/redis',
                                               {'REDIS_HOST': 'redis'})
    create_service(mocked_config)
    deploy_service(mocked_config, deployment_identifier="id-0")
    validate_service(cfn_client, stack_name, expected_string)
    if not keep_resources:
        delete_stack(cfn_client, stack_name, wait=False)


def test_cloudlift_can_revert_service(keep_resources):
    mocked_config = mocked_service_config
    stack_name = f'{service_name}-{environment_name}'
    cfn_client = boto3.client('cloudformation')
    delete_stack(cfn_client, stack_name, wait=True)

    secrets_manager.set_secrets_manager_config(environment_name, stack_name,
                                               {'LABEL': 'Value from secret manager v1', 'PORT': '80'})
    secrets_manager.set_secrets_manager_config(environment_name, f'{stack_name}/redis',
                                               {'REDIS_HOST': 'redis'})
    create_service(mocked_config)
    deploy_service(mocked_config, deployment_identifier='id-1')
    validate_service(
        cfn_client,
        stack_name,
        'This is dummy app. Label: Value from secret manager v1. Redis PING: PONG. AWS EC2 READ ACCESS: True',
    )

    secrets_manager.set_secrets_manager_config(environment_name, f"{service_name}-{environment_name}",
                                               {'LABEL': 'Value from secret manager v2', 'PORT': '80',
                                                'REDIS_HOST': 'redis'})
    deploy_service(mocked_config, deployment_identifier='id-2')
    validate_service(
        cfn_client,
        stack_name,
        'This is dummy app. Label: Value from secret manager v2. Redis PING: PONG. AWS EC2 READ ACCESS: True',
    )

    revert_service(deployment_identifier='id-1')
    validate_service(
        cfn_client,
        stack_name,
        'This is dummy app. Label: Value from secret manager v1. Redis PING: PONG. AWS EC2 READ ACCESS: True',
    )

    assert get_current_task_definition_deployment_identifier(cfn_client, stack_name) == 'id-1'
    if not keep_resources:
        delete_stack(cfn_client, stack_name, wait=False)


def test_cloudlift_service_with_parameter_store_config(keep_resources):
    mocked_config = mocked_service_with_parameter_store_config
    stack_name = f'{service_name}-{environment_name}'
    cfn_client = boto3.client('cloudformation')
    delete_stack(cfn_client, stack_name, wait=True)
    print("adding configuration to parameter store")
    config = {'PORT': '80', 'LABEL': 'Demo', 'REDIS_HOST': 'redis', 'LABEL': 'Value from parameter store v1'}
    _set_param_store_env(environment_name, service_name, config)
    create_service(mocked_config, env_sample_file="parameter-store-env.sample")

    validate_service(
        cfn_client,
        stack_name,
        'This is dummy app. Label: Value from parameter store v1. Redis PING: PONG. AWS EC2 READ ACCESS: True',
    )

    print("adding configuration to parameter store")
    config = {'PORT': '80', 'LABEL': 'Demo', 'REDIS_HOST': 'redis', 'LABEL': 'Value from parameter store v2'}
    _set_param_store_env(environment_name, service_name, config)

    deploy_service(mocked_config, deployment_identifier="id-0", env_sample_file="parameter-store-env.sample")
    validate_service(
        cfn_client,
        stack_name,
        'This is dummy app. Label: Value from parameter store v2. Redis PING: PONG. AWS EC2 READ ACCESS: True',
    )
    if not keep_resources:
        delete_stack(cfn_client, stack_name, wait=False)


def validate_service(cfn_client, stack_name, expected_string):
    outputs = cfn_client.describe_stacks(StackName=stack_name)['Stacks'][0]['Outputs']
    service_url = [x for x in outputs if x["OutputKey"] == "DummyURL"][0]['OutputValue']
    content_matched = wait_until(lambda: match_page_content(service_url, expected_string), 60)
    assert content_matched


def deploy_service(mocked_config, deployment_identifier, env_sample_file="env.sample"):
    os.chdir(f'{TEST_DIR}/dummy')
    with patch.object(ServiceConfiguration, 'get_config',
                      new=mocked_config):
        ServiceUpdater(service_name, environment_name, env_sample_file, timeout_seconds=600,
                       deployment_identifier=deployment_identifier, access_file='access.yml').run()


def revert_service(deployment_identifier):
    os.chdir(f'{TEST_DIR}/dummy')
    ServiceUpdater(service_name, environment_name, timeout_seconds=600,
                   deployment_identifier=deployment_identifier, access_file='access.yml').revert()


def get_current_task_definition_deployment_identifier(cfn_client, stack_name):
    service_arn = cfn_client.describe_stack_resource(StackName=stack_name, LogicalResourceId='Dummy')[
        'StackResourceDetail']['PhysicalResourceId']
    ecs_client = boto3.client('ecs')
    td = ecs_client.describe_services(cluster='cluster-{}'.format(environment_name),
                                      services=[service_arn])['services'][0]['taskDefinition']
    tags = ecs_client.describe_task_definition(taskDefinition=td, include=[
        'TAGS',
    ])['tags']
    return {tag['key']: tag['value'] for tag in tags}.get('deployment_identifier')


def create_service(mocked_config, env_sample_file="env.sample"):
    os.chdir(f'{TEST_DIR}/dummy')
    with patch.object(ServiceConfiguration, 'edit_config',
                      new=mocked_config):
        with patch.object(ServiceConfiguration, 'get_config',
                          new=mocked_config):
            ServiceCreator(service_name, environment_name, env_sample_file, None).create()


def delete_stack(cfn_client, stack_name, wait):
    cfn_client.delete_stack(StackName=stack_name)
    print("initiated delete")
    if wait:
        waiter = cfn_client.get_waiter('stack_delete_complete')
        waiter.wait(StackName=stack_name)
        print("completed delete")


def match_page_content(service_url, content_expected):
    page_content = requests.get(service_url, verify=False).text
    print("page_content: " + str(page_content))
    print("expected: " + content_expected)
    return page_content.strip() == content_expected.strip()


def _set_param_store_env(env_name, svc_name, env_config):
    ssm_client = boto3.client('ssm')
    for env_var in env_config:
        ssm_client.put_parameter(
            Name=f"/{env_name}/{svc_name}/{env_var}",
            Value=env_config[env_var],
            Type="SecureString",
            KeyId='alias/aws/ssm', Overwrite=True
        )

