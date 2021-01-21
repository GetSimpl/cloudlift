from troposphere import Template
from troposphere.ecs import (ContainerDefinition,
                             Environment, Secret,
                             LogConfiguration,
                             PortMapping, TaskDefinition, PlacementConstraint, SystemControl,
                             HealthCheck)

from cloudlift.deployment.launch_types import LAUNCH_TYPE_FARGATE, get_launch_type
from stringcase import camelcase

HARD_LIMIT_MEMORY_IN_MB = 20480


class TaskDefinitionBuilder:
    def __init__(self, environment, service_name, configuration, region):
        self.environment = environment
        self.service_name = service_name
        self.configuration = configuration
        self.region = region

    def build_task_definition(self,
                              container_configurations,
                              ecr_image_uri,
                              fallback_task_role,
                              fallback_task_execution_role,
                              ):
        t = Template()
        t.add_resource(self.build_cloudformation_resource(
            container_configurations,
            ecr_image_uri=ecr_image_uri,
            fallback_task_role=fallback_task_role,
            fallback_task_execution_role=fallback_task_execution_role,
        ))
        task_definition = t.to_dict()["Resources"][self._resource_name(self.service_name)]["Properties"]
        return _cloudformation_to_boto3_payload(task_definition, ignore_keys={'awslogs-group', 'awslogs-region',
                                                                              'awslogs-stream-prefix'})

    def build_cloudformation_resource(
            self,
            container_configurations,
            ecr_image_uri,
            fallback_task_role,
            fallback_task_execution_role,
    ):
        environment = self.environment
        service_name = self.service_name
        config = self.configuration
        launch_type = get_launch_type(config)
        task_family_name = f'{environment}{service_name}Family'[:255]
        td_kwargs = dict()

        td_kwargs['PlacementConstraints'] = [
            PlacementConstraint(Type=constraint['type'],
                                Expression=constraint['expression']) for constraint in
            config.get('placement_constraints', [])
        ]

        td_kwargs['TaskRoleArn'] = config.get('task_role_arn') if 'task_role_arn' in config \
            else fallback_task_role

        td_kwargs['ExecutionRoleArn'] = config.get('task_execution_role_arn') \
            if 'task_execution_role_arn' in config \
            else fallback_task_execution_role

        if ('udp_interface' in config) or ('tcp_interface' in config):
            td_kwargs['NetworkMode'] = 'awsvpc'

        log_config = self._gen_log_config()
        env_config = container_configurations[container_name(service_name)].get('environment', {})
        secrets_config = container_configurations[container_name(service_name)].get('secrets', {})

        cd_kwargs = {
            "Environment": [Environment(Name=name, Value=env_config[name]) for name in env_config],
            "Secrets": [Secret(Name=name, ValueFrom=secrets_config[name]) for name in secrets_config],
            "Name": container_name(service_name),
            "Image": ecr_image_uri,
            "Essential": True,
            "LogConfiguration": log_config,
            "MemoryReservation": int(config['memory_reservation']),
            "Cpu": 0,
            'Memory': int(config.get('memory_hard_limit', HARD_LIMIT_MEMORY_IN_MB)),
        }

        if config['command'] is not None:
            cd_kwargs['Command'] = [config['command']]

        if 'stop_timeout' in config:
            cd_kwargs['StopTimeout'] = int(config['stop_timeout'])

        if 'system_controls' in config:
            cd_kwargs['SystemControls'] = [SystemControl(Namespace=system_control['namespace'],
                                                         Value=system_control['value']) for
                                           system_control in config['system_controls']]

        if launch_type == LAUNCH_TYPE_FARGATE:
            if 'udp_interface' in config:
                raise NotImplementedError('udp interface not yet implemented in fargate type, please use ec2 type')
            elif 'tcp_interface' in config:
                raise NotImplementedError('tcp interface not yet implemented in fargate type, please use ec2 type')

        if 'http_interface' in config:
            cd_kwargs['PortMappings'] = [
                PortMapping(
                    ContainerPort=int(
                        config['http_interface']['container_port']
                    )
                )
            ]
        elif 'udp_interface' in config:
            cd_kwargs['PortMappings'] = [
                PortMapping(ContainerPort=int(config['udp_interface']['container_port']),
                            HostPort=int(config['udp_interface']['container_port']), Protocol='udp'),
                PortMapping(ContainerPort=int(config['udp_interface']['health_check_port']),
                            HostPort=int(config['udp_interface']['health_check_port']), Protocol='tcp')
            ]
        elif 'tcp_interface' in config:
            cd_kwargs['PortMappings'] = [
                PortMapping(ContainerPort=int(config['tcp_interface']['container_port']), Protocol='tcp')
            ]

        if 'container_health_check' in config:
            configured_health_check = config['container_health_check']
            ecs_health_check = {'Command': ['CMD-SHELL', configured_health_check['command']]}
            if 'start_period' in configured_health_check:
                ecs_health_check['StartPeriod'] = int(configured_health_check['start_period'])
            if 'retries' in configured_health_check:
                ecs_health_check['Retries'] = int(configured_health_check['retries'])
            if 'interval' in configured_health_check:
                ecs_health_check['Interval'] = int(configured_health_check['interval'])
            if 'timeout' in configured_health_check:
                ecs_health_check['Timeout'] = int(configured_health_check['timeout'])
            cd_kwargs['HealthCheck'] = HealthCheck(
                **ecs_health_check
            )

        if 'sidecars' in config:
            links = []
            for sidecar in config['sidecars']:
                sidecar_name = sidecar.get('name')
                links.append(
                    "{}:{}".format(container_name(sidecar_name), sidecar_name)
                )
            cd_kwargs['Links'] = links

        if 'container_labels' in config:
            cd_kwargs['DockerLabels'] = config.get('container_labels')

        cd = ContainerDefinition(**cd_kwargs)
        container_definitions = [cd]
        if 'sidecars' in config:
            for sidecar in config['sidecars']:
                container_definitions.append(
                    self._gen_container_definitions_for_sidecar(sidecar,
                                                                log_config,
                                                                container_configurations.get(
                                                                    container_name(sidecar.get('name')),
                                                                    {})),
                )
        if launch_type == LAUNCH_TYPE_FARGATE:
            td_kwargs['RequiresCompatibilities'] = [LAUNCH_TYPE_FARGATE]
            td_kwargs['NetworkMode'] = 'awsvpc'
            td_kwargs['Cpu'] = str(config['fargate']['cpu'])
            td_kwargs['Memory'] = str(config['fargate']['memory'])

        return TaskDefinition(
            self._resource_name(service_name),
            Family=task_family_name,
            ContainerDefinitions=container_definitions,
            **td_kwargs
        )

    def _resource_name(self, service_name):
        return service_name + "TaskDefinition"

    def _gen_log_config(self):
        env_log_group = '-'.join([self.environment, 'logs'])
        return LogConfiguration(
            LogDriver="awslogs",
            Options={
                'awslogs-stream-prefix': self.service_name,
                'awslogs-group': self.configuration.get('log_group', env_log_group),
                'awslogs-region': self.region
            }
        )

    def _gen_container_definitions_for_sidecar(self, sidecar, log_config, env_config):
        cd = dict()

        if 'command' in sidecar:
            cd['Command'] = sidecar['command']

        return ContainerDefinition(
            Name=container_name(sidecar.get('name')),
            Environment=[Environment(Name=k, Value=v) for (k, v) in env_config],
            MemoryReservation=int(sidecar.get('memory_reservation')),
            Image=sidecar.get('image'),
            LogConfiguration=log_config,
            Essential=False,
            **cd
        )


def _cloudformation_to_boto3_payload(data, ignore_keys=set()):
    if not isinstance(data, dict):
        return data

    result = dict()
    for k, v in data.items():
        key = k if k in ignore_keys else camelcase(k)
        if isinstance(v, dict):
            result[key] = _cloudformation_to_boto3_payload(v, ignore_keys)
        elif isinstance(v, list):
            elements = list()
            for each in v:
                elements.append(_cloudformation_to_boto3_payload(each, ignore_keys))
            result[key] = elements
        elif isinstance(v, str):
            if v == 'true' or v == 'false':
                result[key] = v == 'true'
            else:
                result[key] = v
        else:
            result[key] = v
    return result


def container_name(service_name):
    return service_name + "Container"
