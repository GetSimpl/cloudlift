import os

from stringcase import pascalcase
from troposphere.ecs import (ContainerDefinition,
                             Environment,
                             LogConfiguration,
                             TaskDefinition)

from cloudlift.config.logging import log_bold, log_intent, log_warning
from cloudlift.deployment import EcrClient, UnrecoverableException, EcsClient, DeployAction, EcsTaskDefinition
from cloudlift.deployment.deployer import build_config, print_task_diff


def _complete_image_url(ecr_client: EcrClient):
    return ecr_client.ecr_image_uri + ':' + ecr_client.version


class TaskDefinitionCreator:
    def __init__(self, name, environment, version, build_args, region='ap-south-1'):
        self.name = name
        self.environment = environment
        self.build_args = build_args
        self.region = region
        self.version = version
        self.env_sample_file = './env.sample'
        self.cluster_name = f'cluster-{self.environment}'
        self.name_with_env = f"{pascalcase(self.name)}{pascalcase(self.environment)}"

    def create(self):
        log_warning("Create task definition to {self.region}".format(**locals()))
        if not os.path.exists(self.env_sample_file):
            raise UnrecoverableException('env.sample not found. Exiting.')
        ecr_client = EcrClient(self.name, self.region, self.build_args)
        ecr_client.set_version(self.version)
        log_intent("name: " + self.name + " | environment: " +
                   self.environment + " | version: " + str(ecr_client.version))
        log_bold("Checking image in ECR")
        ecr_client.build_and_upload_image()
        log_bold("Creating task definition\n")
        env_config = build_config(self.environment, self.name, self.env_sample_file)
        container_definition_arguments = {
            "environment": [
                {
                    "name": k,
                    "value": v
                } for (k, v) in env_config
            ],
            "name": pascalcase(self.name) + "Container",
            "image": _complete_image_url(ecr_client),
            "essential": True,
            "logConfiguration": self._gen_log_config(pascalcase(self.name)),
            "memoryReservation": 1024
        }

        ecs_client = EcsClient(region=self.region)
        ecs_client.register_task_definition(self._task_defn_family(), [container_definition_arguments], [], None)
        log_bold("Task definition successfully created\n")

    def update(self):
        log_warning("Update task definition to {self.region}".format(**locals()))
        if not os.path.exists(self.env_sample_file):
            raise UnrecoverableException('env.sample not found. Exiting.')
        ecr_client = EcrClient(self.name, self.region, self.build_args)
        ecr_client.set_version(self.version)
        log_intent("name: " + self.name + " | environment: " +
                   self.environment + " | version: " + str(ecr_client.version))
        log_bold("Checking image in ECR")
        ecr_client.build_and_upload_image()
        log_bold("Updating task definition\n")
        env_config = build_config(self.environment, self.name, self.env_sample_file)
        ecs_client = EcsClient(region=self.region)
        deployment = DeployAction(ecs_client, self.cluster_name, None)
        task_defn = self._apply_changes_over_current_task_defn(env_config, ecs_client, ecr_client, deployment)
        deployment.update_task_definition(task_defn)
        log_bold("Task definition successfully updated\n")

    def _current_task_defn(self, ecs_client: EcsClient, deployment: DeployAction):
        task_defn_arn = ecs_client.list_task_definitions(self._task_defn_family())[0]
        return deployment.get_task_definition(task_defn_arn)

    def _apply_changes_over_current_task_defn(self, env_config, ecs_client: EcsClient, ecr_client: EcrClient,
                                              deployment: DeployAction):
        current_task_defn = self._current_task_defn(ecs_client, deployment)
        container_name = current_task_defn['containerDefinitions'][0]['name']
        current_task_defn.set_images(
            ecr_client.version,
            **{container_name: _complete_image_url(ecr_client)}
        )
        for container in current_task_defn.containers:
            current_task_defn.apply_container_environment(container, env_config)
        print_task_diff(self.name, current_task_defn.diff, 'white')
        return current_task_defn

    def _task_defn_family(self):
        return f"{self.name_with_env}Family"

    def _gen_log_config(self, stream_prefix):
        return {
            'logDriver': 'awslogs',
            'options': {
                'awslogs-stream-prefix': stream_prefix,
                'awslogs-group': '-'.join([self.environment, 'logs']),
                'awslogs-region': self.region
            }
        }
