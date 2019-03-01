import sys
from time import sleep

from colorclass import Color
from terminaltables import SingleTable

from config.parameter_store import ParameterStore
from deployment.ecs import DeployAction
from deployment.logging import log_bold, log_err, log_intent, log_with_color


def deploy_new_version(client, cluster_name, ecs_service_name,
                       deploy_version_tag, service_name, sample_env_file_path,
                       env_name, color='white', complete_image_uri=None):
    env_config = build_config(env_name, service_name, sample_env_file_path)
    deployment = DeployAction(client, cluster_name, ecs_service_name)
    if deployment.service.desired_count == 0:
        desired_count = 1
    else:
        desired_count = deployment.service.desired_count
    deployment.service.set_desired_count(desired_count)
    task_definition = deployment.get_current_task_definition(
        deployment.service
    )
    if complete_image_uri is not None:
        container_name = task_definition['containerDefinitions'][0]['name']
        task_definition.set_images(
            deploy_version_tag,
            **{container_name: complete_image_uri}
        )
    else:
        task_definition.set_images(deploy_version_tag)
    for container in task_definition.containers:
        task_definition.apply_container_environment(container, env_config)
    print_task_diff(ecs_service_name, task_definition.diff, color)
    new_task_definition = deployment.update_task_definition(task_definition)
    response = deploy_and_wait(deployment, new_task_definition, color)
    if response:
        log_bold(ecs_service_name + " Deployed successfully.")
    else:
        log_err(ecs_service_name + " Deployment failed.")
    return response


def deploy_and_wait(deployment, new_task_definition, color):
    existing_events = fetch_events(deployment.get_service())
    deployment.deploy(new_task_definition)
    return wait_for_finish(deployment, existing_events, color)


def build_config(env_name, service_name, sample_env_file_path):
    service_config = read_config(open(sample_env_file_path).read())
    try:
        environment_config = ParameterStore(
            service_name,
            env_name).get_existing_config()
    except Exception as err:
        log_intent(str(err))
        log_err("Cannot find the configuration in parameter store \
[env: %s | service: %s]." % (env_name, service_name))
        sys.exit(1)
    missing_env_config = set(service_config) - set(environment_config)
    if missing_env_config:
        log_err('There is no config value for the keys ' +
                str(missing_env_config))
        sys.exit(1)
    missing_env_sample_config = set(environment_config) - set(service_config)
    if missing_env_sample_config:
        log_err('There is no config value for the keys in env.sample file ' +
                str(missing_env_sample_config))
        sys.exit(1)

    return make_container_defn_env_conf(service_config, environment_config)


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


def wait_for_finish(action, existing_events, color):
    waiting = True
    while waiting:
        sleep(1)
        service = action.get_service()
        existing_events = fetch_and_print_new_events(
            service,
            existing_events,
            color
        )
        waiting = not action.is_deployed(service) and not service.errors
    if service.errors:
        log_err(str(service.errors))
        return False
    return True


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
                        '{/'+env_var_diff_color+'}'
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
