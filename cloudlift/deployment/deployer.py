from datetime import datetime
from time import sleep, time

import boto3
from cloudlift.config import ParameterStore
from cloudlift.config.logging import log_bold, log_err, log_intent, log_with_color
from cloudlift.deployment.ecs import DeployAction
from cloudlift.exceptions import UnrecoverableException
from colorclass import Color
from terminaltables import SingleTable
from cloudlift.config import secrets_manager


def find_essential_container(container_definitions):
    for defn in container_definitions:
        if defn[u'essential']:
            return defn[u'name']
    raise UnrecoverableException('no essential containers found')


def revert_deployment(client, cluster_name, ecs_service_name, color, timeout_seconds, deployment_identifier, **kwargs):
    deployment = DeployAction(client, cluster_name, ecs_service_name)
    previous_task_defn = deployment.get_previous_task_definition(deployment.service,deployment_identifier)
    deploy_task_definition(client, previous_task_defn, cluster_name, ecs_service_name, color, timeout_seconds, 'Revert')


def deploy_new_version(client, cluster_name, ecs_service_name, deployment_identifier,
                       deploy_version_tag, service_name, sample_env_file_path,
                       timeout_seconds, env_name, secrets_name, color='white', complete_image_uri=None):
    task_definition = create_new_task_definition(color, complete_image_uri, deploy_version_tag, ecs_service_name,
                                                 env_name, sample_env_file_path, secrets_name, service_name, client,
                                                 cluster_name,deployment_identifier)
    deploy_task_definition(client, task_definition, cluster_name, ecs_service_name, color, timeout_seconds, 'Deploy')


def deploy_task_definition(client, task_definition, cluster_name, ecs_service_name, color, timeout_secs, action_name):
    deployment = DeployAction(client, cluster_name, ecs_service_name)
    log_bold(f"Starting {action_name} for" + ecs_service_name)
    if deployment.service.desired_count == 0:
        desired_count = 1
    else:
        desired_count = deployment.service.desired_count
    deployment.service.set_desired_count(desired_count)
    deployment_succeeded = deploy_and_wait(deployment, task_definition, color, timeout_secs)
    if not deployment_succeeded:
        record_deployment_failure_metric(deployment.cluster_name, deployment.service_name)
        raise UnrecoverableException(ecs_service_name + f" {action_name} failed.")
    log_bold(ecs_service_name + f" {action_name}: Completed successfully.")


def create_new_task_definition(color, complete_image_uri, deploy_version_tag, ecs_service_name, env_name,
                               sample_env_file_path, secrets_name, service_name, client, cluster_name,deployment_identifier):
    deployment = DeployAction(client, cluster_name, ecs_service_name)
    task_definition = deployment.get_current_task_definition(deployment.service)
    essential_container = find_essential_container(task_definition[u'containerDefinitions'])
    container_configurations = build_config(env_name, service_name, sample_env_file_path, essential_container,
                                            secrets_name)
    if complete_image_uri is not None:
        task_definition.set_images(essential_container, deploy_version_tag, **{essential_container: complete_image_uri})
    else:
        task_definition.set_images(essential_container, deploy_version_tag)
    for container in task_definition.containers:
        env_config = container_configurations.get(container['name'], {})
        task_definition.apply_container_environment_and_secrets(container, env_config)
    print_task_diff(ecs_service_name, task_definition.diff, color)
    new_task_definition = deployment.update_task_definition(task_definition,deployment_identifier)
    return new_task_definition


def deploy_and_wait(deployment, new_task_definition, color, timeout_seconds):
    existing_events = fetch_events(deployment.get_service())
    deploy_end_time = time() + timeout_seconds
    deployment.deploy(new_task_definition)
    return wait_for_finish(deployment, existing_events, color, deploy_end_time)


def build_config(env_name, service_name, sample_env_file_path, essential_container_name, secrets_name=None):
    env_config_secrets_mgr = secrets_manager.get_config(secrets_name, env_name) if secrets_name else {}
    env_config_param_store = _get_parameter_store_config(service_name, env_name)
    keys_not_in_secret_mgr = set(env_config_param_store) - set(env_config_secrets_mgr)
    env_config = {k: env_config_param_store[k] for k in keys_not_in_secret_mgr}
    sample_config_keys = set(read_config(open(sample_env_file_path).read()))
    _validate_config_availability(sample_config_keys, set(env_config_param_store).union(set(env_config_secrets_mgr)))
    secrets = {k: env_config_secrets_mgr[k] for k in set(env_config_secrets_mgr).intersection(sample_config_keys)}
    env = {k: env_config[k] for k in set(env_config).intersection(sample_config_keys)}
    return {essential_container_name: {"secrets": secrets, "environment": env}}


def _get_parameter_store_config(service_name, env_name):
    try:
        environment_config, _ = ParameterStore(service_name, env_name).get_existing_config()
    except Exception as err:
        log_intent(str(err))
        ex_msg = f"Cannot find the configuration in parameter store [env: ${env_name} | service: ${service_name}]."
        raise UnrecoverableException(ex_msg)
    return environment_config


def _validate_config_availability(sample_config_keys, environment_var_set):
    missing_actual_config = sample_config_keys - environment_var_set
    if missing_actual_config:
        raise UnrecoverableException('There is no config value for the keys ' + str(missing_actual_config))


def read_config(file_content):
    config = {}
    for line in file_content.splitlines():
        line = line.strip()
        if not line:
            continue
        key, value = line.split('=', 1)
        config[key] = value
    return config


def wait_for_finish(action, existing_events, color, deploy_end_time):
    while time() <= deploy_end_time:
        service = action.get_service()
        existing_events = fetch_and_print_new_events(service, existing_events, color)
        if is_deployed(service):
            return True
        sleep(5)

    log_err("Deployment timed out!")
    return False


def record_deployment_failure_metric(cluster_name, service_name):
    cloudwatch_client = boto3.client('cloudwatch')
    cloudwatch_client.put_metric_data(
        Namespace='ECS/DeploymentMetrics',
        MetricData=[
            {
                "MetricName": 'FailedCloudliftDeployments',
                "Value": 1,
                "Timestamp": datetime.utcnow(),
                "Dimensions": [
                    {
                        'Name': 'ClusterName',
                        'Value': cluster_name
                    },
                    {
                        'Name': 'ServiceName',
                        'Value': service_name
                    }
                ]
            }
        ]
    )


def is_deployed(service):
    if len(service['deployments']) == 1 and service['desiredCount'] == service['runningCount']:
        return True
    return False


def fetch_events(service):
    return sorted(service.get(u'events'), key=lambda k: k['createdAt'])


def fetch_and_print_new_events(service, existing_events, color):
    all_events = fetch_events(service)
    new_events = [evnt for evnt in all_events if evnt not in existing_events]
    for event in new_events:
        log_with_color(event['message'].replace("(", "").replace(")", "")[8:], color)
    return all_events


def print_task_diff(ecs_service_name, diffs, color):
    image_diff = next(x for x in diffs if x.field == 'image')
    if image_diff.old_value != image_diff.value:
        log_with_color(ecs_service_name + " New image getting deployed", color)
        log_with_color(ecs_service_name + " " + str(image_diff), color)
    else:
        log_with_color(ecs_service_name + " No change in image version", color)
    env_diff = next(x for x in diffs if x.field == 'environment')
    table_data = _prepare_diff_table(env_diff)
    if len(table_data) > 1:
        log_with_color(ecs_service_name + " Environment changes", color)
        print(SingleTable(table_data).table)
    else:
        log_with_color(ecs_service_name + " No change in environment variables", color)
    secrets_diff = next(x for x in diffs if x.field == 'secrets')
    table_data = _prepare_diff_table(secrets_diff)
    if len(table_data) > 1:
        log_with_color(ecs_service_name + " Secrets changes", color)
        print(SingleTable(table_data).table)
    else:
        log_with_color(ecs_service_name + " No change in secrets", color)


def _prepare_diff_table(diff):
    old_value, current_value = diff.old_value, diff.value
    keys = sorted(set(diff.old_value.keys()).union(diff.value.keys()))
    table_data = [[
        Color('{autoyellow}Name{/autoyellow}'),
        Color('{autoyellow}Old value{/autoyellow}'),
        Color('{autoyellow}Current value{/autoyellow}')
    ]]
    for env_var in keys:
        old_val = old_value.get(env_var, '-')
        current_val = current_value.get(env_var, '-')
        if old_val != current_val:
            env_var_diff_color = 'autored'
            table_data.append(
                [
                    Color(
                        '{' + env_var_diff_color + '}' +
                        env_var +
                        '{/' + env_var_diff_color + '}'
                    ),
                    old_val,
                    current_val
                ]
            )
    return table_data


def container_name(service_name):
    return service_name + "Container"


def strip_container_name(name):
    return name.replace("Container", "")
