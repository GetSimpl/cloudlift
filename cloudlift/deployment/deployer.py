from os.path import basename
from time import sleep, time
from cloudlift.exceptions import UnrecoverableException
from colorclass import Color
from terminaltables import SingleTable

from cloudlift.config import ParameterStore
from cloudlift.deployment.ecs import DeployAction
from cloudlift.config.logging import log_bold, log_err, log_intent, log_with_color
from datetime import datetime
import boto3
from glob import glob


def find_essential_container(container_definitions):
    for defn in container_definitions:
        if defn[u'essential']:
            return defn[u'name']

    raise UnrecoverableException('no essential containers found')


def deploy_new_version(client, cluster_name, ecs_service_name,
                       deploy_version_tag, service_name, sample_env_file_path,
                       timeout_seconds, env_name, color='white', complete_image_uri=None):
    log_bold("Starting to deploy " + ecs_service_name)
    deployment = DeployAction(client, cluster_name, ecs_service_name)
    if deployment.service.desired_count == 0:
        desired_count = 1
    else:
        desired_count = deployment.service.desired_count
    deployment.service.set_desired_count(desired_count)
    task_definition = deployment.get_current_task_definition(
        deployment.service
    )

    essential_container = find_essential_container(task_definition[u'containerDefinitions'])

    container_configurations = build_config(
        env_name,
        service_name,
        sample_env_file_path,
        essential_container,
    )

    if complete_image_uri is not None:
        task_definition.set_images(
            essential_container,
            deploy_version_tag,
            **{essential_container: complete_image_uri}
        )
    else:
        task_definition.set_images(essential_container, deploy_version_tag)
    for container in task_definition.containers:
        env_config = container_configurations.get(container[u'name'], [])
        task_definition.apply_container_environment(container, env_config)
    print_task_diff(ecs_service_name, task_definition.diff, color)
    new_task_definition = deployment.update_task_definition(task_definition)

    deployment_succeeded = deploy_and_wait(deployment, new_task_definition, color, timeout_seconds)

    if not deployment_succeeded:
        record_deployment_failure_metric(deployment.cluster_name, deployment.service_name)
        raise UnrecoverableException(ecs_service_name + " Deployment failed.")

    log_bold(ecs_service_name + " Deployed successfully.")


def deploy_and_wait(deployment, new_task_definition, color, timeout_seconds):
    existing_events = fetch_events(deployment.get_service())
    deploy_end_time = time() + timeout_seconds
    deployment.deploy(new_task_definition)
    return wait_for_finish(deployment, existing_events, color, deploy_end_time)


def build_config(env_name, cloudlift_service_name, sample_env_file_path, essential_container_name):
    try:
        environment_config, sidecars_configs = ParameterStore(
            cloudlift_service_name,
            env_name).get_existing_config()
    except Exception as err:
        log_intent(str(err))
        raise UnrecoverableException("Cannot find the configuration in parameter store \
[env: %s | service: %s]." % (env_name, cloudlift_service_name))

    sidecar_filename_format = 'sidecar_{}_{}'
    configs_to_check = [(essential_container_name, sample_env_file_path, environment_config)]
    sample_filename = basename(sample_env_file_path)
    for sidecar_name, sidecar_config in sidecars_configs.items():
        configs_to_check.append(
            (container_name(sidecar_name), sidecar_filename_format.format(sidecar_name, sample_filename),
             sidecar_config)
        )

    all_sidecar_env_samples = sorted(glob(sidecar_filename_format.format('*', sample_filename)))
    all_sidecars_in_parameter_store = [sidecar_filename_format.format(name, sample_filename) for name in
                                              sidecars_configs.keys()]

    if all_sidecar_env_samples != all_sidecars_in_parameter_store:
        raise UnrecoverableException('There is a mismatch in sidecar configuratons. '
                                     'Env Samples found: {}, Configurations present for: {}'.format(
            all_sidecar_env_samples,
            all_sidecars_in_parameter_store,
        ))

    container_configurations = {}
    for name, filepath, env_config in configs_to_check:
        sample_config = read_config(open(filepath).read())
        missing_actual_config = set(sample_config) - set(env_config)
        if missing_actual_config:
            raise UnrecoverableException(
                'There is no config value for the keys of container {} '.format(name) +
                str(missing_actual_config))

        missing_sample_config = set(env_config) - set(sample_config)
        if missing_sample_config:
            raise UnrecoverableException('There is no config value for the keys in {} file '.format(filepath) +
                                         str(missing_sample_config))

        container_configurations[name] = make_container_defn_env_conf(sample_config,
                                                                      env_config)

    return container_configurations


def read_config(file_content):
    config = {}
    for line in file_content.splitlines():
        line = line.strip()
        if not line:
            continue
        key, value = line.split('=', 1)
        config[key] = value
    return config


def make_container_defn_env_conf(service_config, environment_config):
    container_defn_env_config = []
    for env_var_name in service_config:
        container_defn_env_config.append(
            (env_var_name, environment_config[env_var_name])
        )
    return container_defn_env_config


def wait_for_finish(action, existing_events, color, deploy_end_time):
    while time() <= deploy_end_time:
        service = action.get_service()
        existing_events = fetch_and_print_new_events(
            service,
            existing_events,
            color
        )

        if is_deployed(service['deployments']):
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


def is_deployed(service_deployments):
    for deployment in service_deployments:
        if deployment['status'] == 'PRIMARY':
            return deployment['desiredCount'] == deployment['runningCount']
    return False


def fetch_events(service):
    all_events = sorted(service.get(u'events'), key=lambda k: k['createdAt'])
    return all_events


def fetch_and_print_new_events(service, existing_events, color):
    all_events = fetch_events(service)
    new_events = [evnt for evnt in all_events if evnt not in existing_events]
    for event in new_events:
        log_with_color(
            event['message'].replace("(", "").replace(")", "")[8:],
            color
        )
    return all_events


def print_task_diff(ecs_service_name, diffs, color):
    image_diff = next(x for x in diffs if x.field == 'image')
    if image_diff.old_value != image_diff.value:
        log_with_color(ecs_service_name + " New image getting deployed", color)
        log_with_color(ecs_service_name + " " + str(image_diff), color)
    else:
        log_with_color(ecs_service_name + " No change in image version", color)
    env_diff = next(x for x in diffs if x.field == 'environment')
    old_env, current_env = env_diff.old_value, env_diff.value
    env_vars = sorted(
        set(env_diff.old_value.keys()).union(env_diff.value.keys())
    )
    table_data = []
    table_data.append(
        [
            Color('{autoyellow}Env. var.{/autoyellow}'),
            Color('{autoyellow}Old value{/autoyellow}'),
            Color('{autoyellow}Current value{/autoyellow}')
        ]
    )
    for env_var in env_vars:
        old_val = old_env.get(env_var, '-')
        current_val = current_env.get(env_var, '-')
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
    if len(table_data) > 1:
        log_with_color(ecs_service_name + " Environment changes", color)
        print(SingleTable(table_data).table)
    else:
        log_with_color(
            ecs_service_name + " No change in environment variables",
            color
        )


def container_name(service_name):
    return service_name + "Container"


def strip_container_name(name):
    return name.replace("Container", "")
