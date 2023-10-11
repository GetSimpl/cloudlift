import json
import re
import uuid

import boto3
from botocore.exceptions import ClientError
from cloudlift.exceptions import UnrecoverableException
from cloudlift.config import get_client_for

from awacs.aws import PolicyDocument, Statement, Allow, Principal
from awacs.sts import AssumeRole
from awacs.firehose import PutRecordBatch
from cfn_flip import to_yaml
from stringcase import pascalcase
from troposphere import GetAtt, Output, Parameter, Ref, Sub, ImportValue, Tags
from troposphere.cloudwatch import Alarm, MetricDimension
from troposphere.ec2 import SecurityGroup
from troposphere.ecs import (AwsvpcConfiguration, ContainerDefinition,
                             DeploymentConfiguration, Secret, MountPoint,
                             LoadBalancer, LogConfiguration, Volume, EFSVolumeConfiguration,
                             NetworkConfiguration, PlacementStrategy,
                             PortMapping, Service, TaskDefinition, ServiceRegistry, PlacementConstraint, 
                             MountPoint, ContainerDependency, Environment,
                             FirelensConfiguration, HealthCheck)
from troposphere.elasticloadbalancingv2 import Action, Certificate, Listener
from troposphere.elasticloadbalancingv2 import LoadBalancer as ALBLoadBalancer
from troposphere.elasticloadbalancingv2 import (Matcher, RedirectConfig,
                                                TargetGroup,
                                                TargetGroupAttribute)
from troposphere.iam import Role, Policy
from troposphere.servicediscovery import Service as SD
from troposphere.servicediscovery import DnsConfig, DnsRecord
from troposphere.events import Rule, Target

from cloudlift.config import region as region_service
from cloudlift.config import get_account_id
from cloudlift.config import DecimalEncoder, VERSION
from cloudlift.config import get_service_stack_name
from cloudlift.deployment.deployer import build_config
from cloudlift.deployment.ecs import DeployAction, EcsClient
from cloudlift.config.logging import log, log_bold
from cloudlift.deployment.service_information_fetcher import ServiceInformationFetcher
from cloudlift.deployment.template_generator import TemplateGenerator
from cloudlift.constants import FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
from cloudlift.config.environment_configuration import EnvironmentConfiguration

class ServiceTemplateGenerator(TemplateGenerator):
    PLACEMENT_STRATEGIES = [
        PlacementStrategy(
            Type='spread',
            Field='attribute:ecs.availability-zone'
        ),
        PlacementStrategy(
            Type='spread',
            Field='instanceId'
        )]
    LAUNCH_TYPE_FARGATE = 'FARGATE'
    LAUNCH_TYPE_EC2 = 'EC2'

    def __init__(self, service_configuration, environment_stack):
        super(ServiceTemplateGenerator, self).__init__(
            service_configuration.environment
        )
        self._derive_configuration(service_configuration)
        self.env_sample_file_path = './env.sample'
        self.environment_stack = environment_stack
        self.current_version = ServiceInformationFetcher(
            self.application_name, self.env).get_current_version()
        self.bucket_name = 'cloudlift-service-template'
        self.environment = service_configuration.environment
        self.client = get_client_for('s3', self.environment)
        self.team_name = (self.notifications_arn.split(':')[-1])
        self.environment_configuration = EnvironmentConfiguration(self.environment).get_config().get(self.environment, {})
    def _derive_configuration(self, service_configuration):
        self.application_name = service_configuration.service_name
        self.configuration = service_configuration.get_config(VERSION)

    def generate_service(self):
        self._add_service_parameters()
        self._add_service_outputs()
        self._fetch_current_desired_count()
        self._add_ecs_service_iam_role()
        self._add_cluster_services()

        key = uuid.uuid4().hex + '.yml'
        if len(to_yaml(self.template.to_json())) > 51000:
            try:
                self.client.put_object(
                    Body=to_yaml(self.template.to_json()),
                    Bucket=self.bucket_name,
                    Key=key,
                )
                template_url = f'https://{self.bucket_name}.s3.amazonaws.com/{key}'
                return template_url, 'TemplateURL', key
            except ClientError as boto_client_error:
                error_code = boto_client_error.response['Error']['Code']
                if error_code == 'AccessDenied':
                    raise UnrecoverableException(f'Unable to store cloudlift service template in S3 bucket at {self.bucket_name}')
                else:
                    raise boto_client_error
        else:
            return to_yaml(self.template.to_json()), 'TemplateBody', ''

    def _add_cluster_services(self):
        for ecs_service_name, config in self.configuration['services'].items():
            self._add_service(ecs_service_name, config)

    def _add_service_alarms(self, svc):
        oom_event_rule = Rule(
            'EcsOOM' + str(svc.name),
            Description="Triggered when an Amazon ECS Task is stopped",
            EventPattern={
                "detail-type": ["ECS Task State Change"],
                "source": ["aws.ecs"],
                "detail": {
                    "clusterArn": [{"anything-but": [str(self.cluster_name)]}],
                    "containers": {
                        "reason": [{
                            "prefix": "OutOfMemory"
                        }]
                    },
                    "desiredStatus": ["STOPPED"],
                    "lastStatus": ["STOPPED"],
                    "taskDefinitionArn": [{
                        "anything-but": [str(svc.name) + "Family"]
                    }]
                }
            },
            State="ENABLED",
            Targets=[Target(
                    Arn=Ref(self.notification_sns_arn),
                    Id="ECSOOMStoppedTasks",
                    InputPath="$.detail.containers[0]"
                )
            ]
        )
        self.template.add_resource(oom_event_rule)

        ecs_high_cpu_alarm = Alarm(
            'EcsHighCPUAlarm' + str(svc.name),
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(
                    Name='ClusterName',
                    Value=self.cluster_name
                ),
                MetricDimension(
                    Name='ServiceName',
                    Value=GetAtt(svc, 'Name')
                )],
            AlarmActions=[Ref(self.notification_sns_arn)],
            OKActions=[Ref(self.notification_sns_arn)],
            AlarmDescription='Alarm if CPU too high or metric disappears \
indicating instance is down',
            Namespace='AWS/ECS',
            Period=300,
            ComparisonOperator='GreaterThanThreshold',
            Statistic='Average',
            Threshold='80',
            MetricName='CPUUtilization'
        )
        self.template.add_resource(ecs_high_cpu_alarm)
        ecs_high_memory_alarm = Alarm(
            'EcsHighMemoryAlarm' + str(svc.name),
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(
                    Name='ClusterName',
                    Value=self.cluster_name
                ),
                MetricDimension(
                    Name='ServiceName',
                    Value=GetAtt(svc, 'Name')
                )
            ],
            AlarmActions=[Ref(self.notification_sns_arn)],
            OKActions=[Ref(self.notification_sns_arn)],
            AlarmDescription='Alarm if memory too high or metric \
disappears indicating instance is down',
            Namespace='AWS/ECS',
            Period=300,
            ComparisonOperator='GreaterThanThreshold',
            Statistic='Average',
            Threshold='120',
            MetricName='MemoryUtilization'
        )
        self.template.add_resource(ecs_high_memory_alarm)
        # How to add service task count alarm
        # http://docs.aws.amazon.com/AmazonECS/latest/developerguide/cloudwatch-metrics.html#cw_running_task_count
        ecs_no_running_tasks_alarm = Alarm(
            'EcsNoRunningTasksAlarm' + str(svc.name),
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(
                    Name='ClusterName',
                    Value=self.cluster_name
                ),
                MetricDimension(
                    Name='ServiceName',
                    Value=GetAtt(svc, 'Name')
                )
            ],
            AlarmActions=[Ref(self.notification_sns_arn)],
            OKActions=[Ref(self.notification_sns_arn)],
            AlarmDescription='Alarm if the task count goes to zero, denoting \
service is down',
            Namespace='AWS/ECS',
            Period=60,
            ComparisonOperator='LessThanThreshold',
            Statistic='SampleCount',
            Threshold='1',
            MetricName='CPUUtilization',
            TreatMissingData='breaching'
        )
        self.template.add_resource(ecs_no_running_tasks_alarm)

    def _add_service(self, service_name, config):
        launch_type = self.LAUNCH_TYPE_FARGATE if 'fargate' in config else self.LAUNCH_TYPE_EC2
        env_config = build_config(
            self.env,
            self.application_name,
            self.env_sample_file_path
        )
        container_definition_arguments = {
            "Secrets": [
                Secret(Name=k, ValueFrom=v) for (k, v) in env_config
            ],
            "Name": service_name + "Container",
            "Image": self.ecr_image_uri + ':' + self.current_version,
            "Essential": 'true',
            "Cpu": 0
        }
        placement_constraint = {}
        if 'fargate' not in config:
            for key in self.environment_stack["Outputs"]:
                if key["OutputKey"] == 'ECSClusterDefaultInstanceLifecycle':
                    spot_deployment = False if ImportValue("{self.env}ECSClusterDefaultInstanceLifecycle".format(**locals())) == 'ondemand' else True
                    placement_constraint = {
                        "PlacementConstraints": [PlacementConstraint(
                            Type='memberOf',
                            Expression='attribute:deployment_type == spot' if spot_deployment else 'attribute:deployment_type == ondemand'
                        )],
                    }
            if 'spot_deployment' in config:
                spot_deployment = config["spot_deployment"]
                placement_constraint = {
                    "PlacementConstraints" : [PlacementConstraint(
                        Type='memberOf',
                        Expression='attribute:deployment_type == spot' if spot_deployment else 'attribute:deployment_type == ondemand'
                    )],
                }

        if 'http_interface' in config:
            container_definition_arguments['PortMappings'] = [
                PortMapping(
                    ContainerPort=int(
                        config['http_interface']['container_port']
                    )
                )
            ]

        if 'logging' not in config:
            service_defaults = self.environment_configuration.get('service_defaults', {})
            default_logging = service_defaults.get('logging')
            if default_logging:
                # Side Effect
                # This assignment ensures 'config' has the default logging key for future operations
                config['logging'] = default_logging 

        if 'logging' not in config or 'logging' in config and config['logging'] is not None:
            log_type = "awslogs" if 'logging' not in config else config['logging']
            container_definition_arguments['LogConfiguration'] = self._gen_log_config(service_name, log_type)

        if config['command'] is not None:
            container_definition_arguments['Command'] = [config['command']]

        if 'volume' in config:
            container_definition_arguments['MountPoints'] = [MountPoint(
                SourceVolume=service_name + '-efs-volume',
                ContainerPath=config['volume']['container_path']
            )]
        if launch_type == self.LAUNCH_TYPE_EC2:
            container_definition_arguments['MemoryReservation'] = int(config['memory_reservation'])
            container_definition_arguments['Memory'] = int(config['memory_reservation']) + -(-(int(config['memory_reservation']) * 50 )//100) # Celling the value

        cd = ContainerDefinition(**self._firelens_container_def_args_override(config, container_definition_arguments))

        task_role_args = {}
        if config.get("logging") == "awsfirelens":
            service_defaults = self.environment_configuration.get('service_defaults', {})
            assume_role_resource = service_defaults.get('env', {}).get('kinesis_role_arn')
            task_role_args["Policies"] = [
                Policy(
                    PolicyName=service_name + "-Firelens",
                    PolicyDocument=PolicyDocument(
                        Statement=[
                            Statement(
                                Effect=Allow,
                                Action=[AssumeRole],
                                Resource=[assume_role_resource or "*"],
                            )
                        ]
                    ),
                )
            ]

        task_role = self.template.add_resource(Role(
            service_name + "Role",
            AssumeRolePolicyDocument=PolicyDocument(
                Statement=[
                    Statement(
                        Effect=Allow,
                        Action=[AssumeRole],
                        Principal=Principal("Service", ["ecs-tasks.amazonaws.com"])
                    )
                ]
            ),
            **task_role_args
        ))

        launch_type_td = {}
        if launch_type == self.LAUNCH_TYPE_FARGATE:
            launch_type_td = {
                'RequiresCompatibilities': ['FARGATE'],
                'NetworkMode': 'awsvpc',
                'Cpu': str(config['fargate']['cpu']),
                'Memory': str(config['fargate']['memory'])
            }

        if 'custom_metrics' in config:
            launch_type_td['NetworkMode'] = 'awsvpc'
        if 'volume' in config:
            launch_type_td['Volumes'] = [Volume(
                Name=service_name + '-efs-volume',
                EFSVolumeConfiguration=EFSVolumeConfiguration(
                    FilesystemId=config['volume']['efs_id'],
                    RootDirectory=config['volume']['efs_directory_path']
                )
            )]

        sidecar_container_defs = self._sidecar_container_defs(config, service_name)
        td = TaskDefinition(
            service_name + "TaskDefinition",
            Family=service_name + "Family",
            ContainerDefinitions=[cd] + sidecar_container_defs,
            ExecutionRoleArn=boto3.resource('iam').Role('ecsTaskExecutionRole').arn,
            TaskRoleArn=Ref(task_role),
            Tags=Tags(Team=self.team_name, environment=self.env),
            **launch_type_td
        )
        if 'custom_metrics' in config:
            sd = SD(
                service_name + "ServiceRegistry",
                DnsConfig=DnsConfig(
                    RoutingPolicy="MULTIVALUE",
                    DnsRecords=[DnsRecord(
                        TTL="60",
                        Type="SRV"
                    )],
                    NamespaceId=ImportValue(
                    "{self.env}Cloudmap".format(**locals()))
                ),
                Tags=Tags(
                    {'METRICS_PATH': config['custom_metrics']['metrics_path']},
                    {'METRICS_PORT': config['custom_metrics']['metrics_port']}
                )
            )
            self.template.add_resource(sd)

        self.template.add_resource(td)
        desired_count = self._get_desired_task_count_for_service(service_name)
        deployment_configuration = DeploymentConfiguration(
            MinimumHealthyPercent=100,
            MaximumPercent=200
        )
        if 'http_interface' in config:
            alb, lb, service_listener, alb_sg = self._add_alb(cd, service_name, config, launch_type)

            if launch_type == self.LAUNCH_TYPE_FARGATE:
                # if launch type is ec2, then services inherit the ec2 instance security group
                # otherwise, we need to specify a security group for the service
                launch_type_svc = {}
                if 'custom_metrics' in config:
                    launch_type_svc = {
                        "ServiceRegistries": [ServiceRegistry(
                            RegistryArn=GetAtt(sd, 'Arn'),
                            Port=int(
                                config['custom_metrics']['metrics_port'])
                        )]
                    }
                else:
                    service_security_group = SecurityGroup(
                        pascalcase("FargateService" + self.env + service_name),
                        GroupName=pascalcase("FargateService" + self.env + service_name),
                        SecurityGroupIngress=[{
                            'IpProtocol': 'TCP',
                            'SourceSecurityGroupId': Ref(alb_sg),
                            'ToPort': int(config['http_interface']['container_port']),
                            'FromPort': int(config['http_interface']['container_port']),
                        }],
                        VpcId=Ref(self.vpc),
                        GroupDescription=pascalcase("FargateService" + self.env + service_name),
                        Tags=Tags(Team=self.team_name, environment=self.env)
                    )
                    self.template.add_resource(service_security_group)

                launch_type_svc['NetworkConfiguration'] = NetworkConfiguration(
                    AwsvpcConfiguration=AwsvpcConfiguration(
                        Subnets=[
                            Ref(self.private_subnet1),
                            Ref(self.private_subnet2)
                        ],
                        SecurityGroups=[
                            ImportValue("{self.env}Ec2Host".format(**locals())) if 'custom_metrics' in config else Ref(service_security_group)
                        ]
                    )
                )
            else:
                if 'custom_metrics' in config:
                    launch_type_svc = {
                        "ServiceRegistries": [ServiceRegistry(
                            RegistryArn=GetAtt(sd, 'Arn'),
                            Port=int(
                                config['custom_metrics']['metrics_port'])
                        )],
                        "NetworkConfiguration": NetworkConfiguration(
                            AwsvpcConfiguration=AwsvpcConfiguration(
                                SecurityGroups=[
                                    ImportValue(
                                        "{self.env}Ec2Host".format(**locals()))
                                ],
                                Subnets=[
                                    Ref(self.private_subnet1),
                                    Ref(self.private_subnet2)
                                ]
                            )
                        ),
                        'PlacementStrategies': self.PLACEMENT_STRATEGIES
                    }
                else:
                    launch_type_svc = {
                        'Role': Ref(self.ecs_service_role),
                        'PlacementStrategies': self.PLACEMENT_STRATEGIES
                    }

            svc = Service(
                service_name,
                LoadBalancers=[lb],
                Cluster=self.cluster_name,
                TaskDefinition=Ref(td),
                DesiredCount=desired_count,
                DependsOn=service_listener.title,
                LaunchType=launch_type,
                **launch_type_svc,
                Tags=Tags(Team=self.team_name, environment=self.env),
                **placement_constraint
            )
            self.template.add_output(
                Output(
                    service_name + 'EcsServiceName',
                    Description='The ECS name which needs to be entered',
                    Value=GetAtt(svc, 'Name')
                )
            )
            self.template.add_output(
                Output(
                    service_name + "URL",
                    Description="The URL at which the service is accessible",
                    Value=Sub("https://${" + alb.name + ".DNSName}")
                )
            )
            self.template.add_resource(svc)
        else:
            launch_type_svc = {}
            if launch_type == self.LAUNCH_TYPE_FARGATE:
                # if launch type is ec2, then services inherit the ec2 instance security group
                # otherwise, we need to specify a security group for the service
                if 'custom_metrics' in config:
                    launch_type_svc = {
                        "ServiceRegistries": [ServiceRegistry(
                            RegistryArn=GetAtt(sd, 'Arn'),
                            Port=int(
                                config['custom_metrics']['metrics_port'])
                        )],
                        'NetworkConfiguration': NetworkConfiguration(
                            AwsvpcConfiguration=AwsvpcConfiguration(
                                Subnets=[
                                    Ref(self.private_subnet1),
                                    Ref(self.private_subnet2)
                                ],
                                SecurityGroups=[
                                    ImportValue(
                                        "{self.env}Ec2Host".format(**locals()))
                                ]
                            )
                        )
                    }
                else:
                    service_security_group = SecurityGroup(
                        pascalcase("FargateService" + self.env + service_name),
                        GroupName=pascalcase("FargateService" + self.env + service_name),
                        SecurityGroupIngress=[],
                        VpcId=Ref(self.vpc),
                        GroupDescription=pascalcase("FargateService" + self.env + service_name),
                        Tags=Tags(Team=self.team_name, environment=self.env)
                    )
                    self.template.add_resource(service_security_group)
                    launch_type_svc = {
                        'NetworkConfiguration': NetworkConfiguration(
                            AwsvpcConfiguration=AwsvpcConfiguration(
                                Subnets=[
                                    Ref(self.private_subnet1),
                                    Ref(self.private_subnet2)
                                ],
                                SecurityGroups=[
                                    Ref(service_security_group)
                                ]
                            )
                        )
                    }
            else:
                if 'custom_metrics' in config:
                    launch_type_svc = {
                        "ServiceRegistries": [ServiceRegistry(
                            RegistryArn=GetAtt(sd, 'Arn'),
                            Port=int(
                                config['custom_metrics']['metrics_port'])
                        )],
                        "NetworkConfiguration": NetworkConfiguration(
                            AwsvpcConfiguration=AwsvpcConfiguration(
                                SecurityGroups=[
                                    ImportValue(
                                        "{self.env}Ec2Host".format(**locals()))
                                ],
                                Subnets=[
                                    Ref(self.private_subnet1),
                                    Ref(self.private_subnet2)
                                ]
                            )
                        ),
                        'PlacementStrategies': self.PLACEMENT_STRATEGIES
                    }
                else:
                    launch_type_svc = {
                        'PlacementStrategies': self.PLACEMENT_STRATEGIES
                    }
            svc = Service(
                service_name,
                Cluster=self.cluster_name,
                TaskDefinition=Ref(td),
                DesiredCount=desired_count,
                DeploymentConfiguration=deployment_configuration,
                LaunchType=launch_type,
                **launch_type_svc,
                Tags=Tags(Team=self.team_name, environment=self.env),
                **placement_constraint
            )
            self.template.add_output(
                Output(
                    service_name + 'EcsServiceName',
                    Description='The ECS name which needs to be entered',
                    Value=GetAtt(svc, 'Name')
                )
            )
            self.template.add_resource(svc)
        self._add_service_alarms(svc)

    def _gen_log_config(self, service_name, config):
        if config == 'awslogs':
            return LogConfiguration(
                LogDriver="awslogs",
                Options={
                    'awslogs-stream-prefix': service_name,
                    'awslogs-group': '-'.join([self.env, 'logs']),
                    'awslogs-region': self.region
                }
            )
        elif config == 'fluentd':
            return LogConfiguration(
                LogDriver="fluentd",
                Options={
                    'fluentd-address': 'unix:///var/run/fluent.sock',
                    'labels': 'com.amazonaws.ecs.cluster,com.amazonaws.ecs.container-name,com.amazonaws.ecs.task-arn,com.amazonaws.ecs.task-definition-family,com.amazonaws.ecs.task-definition-version',
                    'fluentd-async': 'true'
                }
            )
        elif config == 'awsfirelens':
            return LogConfiguration(
                LogDriver="awsfirelens"
            )
        return LogConfiguration(
            LogDriver="none"
        )

    def _add_alb(self, cd, service_name, config, launch_type):
        sg_name = 'SG' + self.env + service_name
        svc_alb_sg = SecurityGroup(
            re.sub(r'\W+', '', sg_name),
            GroupName=self.env + '-' + service_name,
            SecurityGroupIngress=self._generate_alb_security_group_ingress(
                config
            ),
            VpcId=Ref(self.vpc),
            GroupDescription=Sub(service_name + "-alb-sg"),
            Tags=Tags(Team=self.team_name, environment=self.env)
        )
        self.template.add_resource(svc_alb_sg)
        alb_name = service_name + pascalcase(self.env)
        if config['http_interface']['internal']:
            alb_subnets = [
                Ref(self.private_subnet1),
                Ref(self.private_subnet2)
            ]
            scheme = "internal"
            if len(alb_name) > 32:
                alb_name = service_name[:32-len(self.env[:4])-len(scheme)] + \
                    pascalcase(self.env)[:4] + "Internal"
            else:
                alb_name += 'Internal'
                alb_name = alb_name[:32]
            alb = ALBLoadBalancer(
                'ALB' + service_name,
                Subnets=alb_subnets,
                SecurityGroups=[
                    self.alb_security_group,
                    Ref(svc_alb_sg)
                ],
                Name=alb_name,
                Tags=[
                    {'Value': alb_name, 'Key': 'Name'},
                    {"Key": "Team", "Value": self.team_name},
                    {'Key': 'environment', 'Value': self.env}
                ],
                Scheme=scheme
            )
        else:
            alb_subnets = [
                Ref(self.public_subnet1),
                Ref(self.public_subnet2)
            ]
            if len(alb_name) > 32:
                alb_name = service_name[:32-len(self.env)] + pascalcase(self.env)
            alb = ALBLoadBalancer(
                'ALB' + service_name,
                Subnets=alb_subnets,
                SecurityGroups=[
                    self.alb_security_group,
                    Ref(svc_alb_sg)
                ],
                Name=alb_name,
                Tags=[
                    {'Value': alb_name, 'Key': 'Name'},
                    {"Key": "Team", "Value": self.team_name},
                    {'Key': 'environment', 'Value': self.env}
                ]
            )

        self.template.add_resource(alb)

        target_group_name = "TargetGroup" + service_name
        health_check_path = config['http_interface']['health_check_path'] if 'health_check_path' in config['http_interface'] else "/elb-check"
        if config['http_interface']['internal']:
            target_group_name = target_group_name + 'Internal'

        target_group_config = {}
        if launch_type == self.LAUNCH_TYPE_FARGATE or 'custom_metrics' in config:
            target_group_config['TargetType'] = 'ip'

        service_target_group = TargetGroup(
            target_group_name,
            HealthCheckPath=health_check_path,
            HealthyThresholdCount=2,
            HealthCheckIntervalSeconds=30,
            TargetGroupAttributes=[
                TargetGroupAttribute(
                    Key='deregistration_delay.timeout_seconds',
                    Value='30'
                )
            ],
            VpcId=Ref(self.vpc),
            Protocol="HTTP",
            Matcher=Matcher(HttpCode="200-399"),
            Port=int(config['http_interface']['container_port']),
            HealthCheckTimeoutSeconds=10,
            UnhealthyThresholdCount=3,
            **target_group_config,
            Tags=[
                {"Key": "Team", "Value": self.team_name},
                {'Key': 'environment', 'Value': self.env}
            ]
        )

        self.template.add_resource(service_target_group)
        # Note: This is a ECS Loadbalancer definition. Not an ALB.
        # Defining this causes the target group to add a target to the correct
        # port in correct ECS cluster instance for the service container.
        lb = LoadBalancer(
            ContainerName=cd.Name,
            TargetGroupArn=Ref(service_target_group),
            ContainerPort=int(config['http_interface']['container_port'])
        )
        target_group_action = Action(
            TargetGroupArn=Ref(target_group_name),
            Type="forward"
        )
        service_listener = self._add_service_listener(
            service_name,
            target_group_action,
            alb,
            config['http_interface']['internal']
        )
        self._add_alb_alarms(service_name, alb)
        return alb, lb, service_listener, svc_alb_sg

    def _add_service_listener(self, service_name, target_group_action,
                              alb, internal):
        ssl_cert = Certificate(CertificateArn=self.ssl_certificate_arn)
        service_listener = Listener(
            "SslLoadBalancerListener" + service_name,
            Protocol="HTTPS",
            DefaultActions=[target_group_action],
            LoadBalancerArn=Ref(alb),
            Port=443,
            Certificates=[ssl_cert],
            SslPolicy="ELBSecurityPolicy-FS-1-2-Res-2019-08"
        )
        self.template.add_resource(service_listener)
        if internal:
            # Allow HTTP traffic on internal services
            http_service_listener = Listener(
                "LoadBalancerListener" + service_name,
                Protocol="HTTP",
                DefaultActions=[target_group_action],
                LoadBalancerArn=Ref(alb),
                Port=80
            )
            self.template.add_resource(http_service_listener)
        else:
            # Redirect HTTP to HTTPS on external services
            redirection_config = RedirectConfig(
                StatusCode='HTTP_301',
                Protocol='HTTPS',
                Port='443'
            )
            http_redirection_action = Action(
                RedirectConfig=redirection_config,
                Type="redirect"
            )
            http_redirection_listener = Listener(
                "LoadBalancerRedirectionListener" + service_name,
                Protocol="HTTP",
                DefaultActions=[http_redirection_action],
                LoadBalancerArn=Ref(alb),
                Port=80
            )
            self.template.add_resource(http_redirection_listener)
        return service_listener

    def _add_alb_alarms(self, service_name, alb):
        unhealthy_alarm = Alarm(
            'ElbUnhealthyHostAlarm' + service_name,
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(
                    Name='LoadBalancer',
                    Value=GetAtt(alb, 'LoadBalancerFullName')
                )
            ],
            AlarmActions=[Ref(self.notification_sns_arn)],
            OKActions=[Ref(self.notification_sns_arn)],
            AlarmDescription='Triggers if any host is marked unhealthy',
            Namespace='AWS/ApplicationELB',
            Period=60,
            ComparisonOperator='GreaterThanOrEqualToThreshold',
            Statistic='Sum',
            Threshold='1',
            MetricName='UnHealthyHostCount',
            TreatMissingData='notBreaching'
        )
        self.template.add_resource(unhealthy_alarm)
        rejected_connections_alarm = Alarm(
            'ElbRejectedConnectionsAlarm' + service_name,
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(
                    Name='LoadBalancer',
                    Value=GetAtt(alb, 'LoadBalancerFullName')
                )
            ],
            AlarmActions=[Ref(self.notification_sns_arn)],
            OKActions=[Ref(self.notification_sns_arn)],
            AlarmDescription='Triggers if load balancer has \
rejected connections because the load balancer \
had reached its maximum number of connections.',
            Namespace='AWS/ApplicationELB',
            Period=60,
            ComparisonOperator='GreaterThanOrEqualToThreshold',
            Statistic='Sum',
            Threshold='1',
            MetricName='RejectedConnectionCount',
            TreatMissingData='notBreaching'
        )
        self.template.add_resource(rejected_connections_alarm)
        http_code_elb5xx_alarm = Alarm(
            'ElbHTTPCodeELB5xxAlarm' + service_name,
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(
                    Name='LoadBalancer',
                    Value=GetAtt(alb, 'LoadBalancerFullName')
                )
            ],
            AlarmActions=[Ref(self.notification_sns_arn)],
            OKActions=[Ref(self.notification_sns_arn)],
            AlarmDescription='Triggers if 5xx response originated \
from load balancer',
            Namespace='AWS/ApplicationELB',
            Period=60,
            ComparisonOperator='GreaterThanOrEqualToThreshold',
            Statistic='Sum',
            Threshold='3',
            MetricName='HTTPCode_ELB_5XX_Count',
            TreatMissingData='notBreaching'
        )
        self.template.add_resource(http_code_elb5xx_alarm)

    def _generate_alb_security_group_ingress(self, config):
        ingress_rules = []
        for access_ip in config['http_interface']['restrict_access_to']:
            if access_ip.find('/') == -1:
                access_ip = access_ip + '/32'
            ingress_rules.append({
                'ToPort': 80,
                'IpProtocol': 'TCP',
                'FromPort': 80,
                'CidrIp': access_ip
            })
            ingress_rules.append({
                'ToPort': 443,
                'IpProtocol': 'TCP',
                'FromPort': 443,
                'CidrIp': access_ip
            })
        return ingress_rules

    def _add_ecs_service_iam_role(self):
        role_name = Sub('ecs-svc-${AWS::StackName}-${AWS::Region}')
        assume_role_policy = {
            u'Statement': [
                {
                    u'Action': [u'sts:AssumeRole'],
                    u'Effect': u'Allow',
                    u'Principal': {
                        u'Service': [u'ecs.amazonaws.com']
                    }
                }
            ]
        }
        self.ecs_service_role = Role(
            'ECSServiceRole',
            Path='/',
            ManagedPolicyArns=[
                'arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceRole'
            ],
            RoleName=role_name,
            AssumeRolePolicyDocument=assume_role_policy
        )
        self.template.add_resource(self.ecs_service_role)

    def _add_service_outputs(self):
        self.template.add_output(Output(
            "CloudliftOptions",
            Description="Options used with cloudlift when \
building this service",
            Value=json.dumps(
                self.configuration,
                cls=DecimalEncoder
            )
        ))
        self._add_stack_outputs()

    def _add_service_parameters(self):
        self.notification_sns_arn = Parameter(
            "NotificationSnsArn",
            Description='',
            Type="String",
            Default=self.notifications_arn)
        self.template.add_parameter(self.notification_sns_arn)
        self.vpc = Parameter(
            "VPC",
            Description='',
            Type="AWS::EC2::VPC::Id",
            Default=list(
                filter(
                    lambda x: x['OutputKey'] == "VPC",
                    self.environment_stack['Outputs']
                )
            )[0]['OutputValue']
        )
        self.template.add_parameter(self.vpc)
        self.public_subnet1 = Parameter(
            "PublicSubnet1",
            Description='',
            Type="AWS::EC2::Subnet::Id",
            Default=list(
                filter(
                    lambda x: x['OutputKey'] == "PublicSubnet1",
                    self.environment_stack['Outputs']
                )
            )[0]['OutputValue']
        )
        self.template.add_parameter(self.public_subnet1)
        self.public_subnet2 = Parameter(
            "PublicSubnet2",
            Description='',
            Type="AWS::EC2::Subnet::Id",
            Default=list(
                filter(
                    lambda x: x['OutputKey'] == "PublicSubnet2",
                    self.environment_stack['Outputs']
                )
            )[0]['OutputValue']
        )
        self.template.add_parameter(self.public_subnet2)
        self.private_subnet1 = Parameter(
            "PrivateSubnet1",
            Description='',
            Type="AWS::EC2::Subnet::Id",
            Default=list(
                filter(
                    lambda x: x['OutputKey'] == "PrivateSubnet1",
                    self.environment_stack['Outputs']
                )
            )[0]['OutputValue']
        )
        self.template.add_parameter(self.private_subnet1)
        self.private_subnet2 = Parameter(
            "PrivateSubnet2",
            Description='',
            Type="AWS::EC2::Subnet::Id",
            Default=list(
                filter(
                    lambda x: x['OutputKey'] == "PrivateSubnet2",
                    self.environment_stack['Outputs']
                )
            )[0]['OutputValue']
        )
        self.template.add_parameter(self.private_subnet2)
        self.template.add_parameter(Parameter(
            "Environment",
            Description='',
            Type="String",
            Default="production"
        ))
        self.alb_security_group = list(
            filter(
                lambda x: x['OutputKey'] == "SecurityGroupAlb",
                self.environment_stack['Outputs']
            )
        )[0]['OutputValue']

    def _fetch_current_desired_count(self):
        stack_name = get_service_stack_name(self.env, self.application_name)
        self.desired_counts = {}
        try:
            stack = region_service.get_client_for(
                'cloudformation',
                self.env
            ).describe_stacks(StackName=stack_name)['Stacks'][0]
            ecs_service_outputs = filter(
                lambda x: x['OutputKey'].endswith('EcsServiceName'),
                stack['Outputs']
            )
            ecs_service_names = []
            for service_name in ecs_service_outputs:
                ecs_service_names.append({
                    "key": service_name['OutputKey'],
                    "value": service_name['OutputValue']
                })
            ecs_client = EcsClient(None, None, self.region)
            for service_name in ecs_service_names:
                deployment = DeployAction(
                    ecs_client,
                    self.cluster_name,
                    service_name["value"]
                )
                actual_service_name = service_name["key"]. \
                    replace("EcsServiceName", "")
                self.desired_counts[actual_service_name] = deployment. \
                    service.desired_count
            log("Existing service counts: " + str(self.desired_counts))
        except Exception:
            log_bold("Could not find existing services.")

    def _get_desired_task_count_for_service(self, service_name):
        if service_name in self.desired_counts:
            return self.desired_counts[service_name]
        else:
            return 0
        
    def _firelens_container_def_args_override(self, configuration, container_def_args):
        logging_type = configuration.get("logging")
        firelens_dependency = ContainerDependency(
            ContainerName=FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME, Condition="START"
        )

        if logging_type == "awsfirelens":
            dependencies = container_def_args.get("DependsOn", [])

            is_firelens_dependency_present = any(
                isinstance(dep, ContainerDependency)
                and dep.ContainerName == FLUENTBIT_FIRELENS_SIDECAR_CONTAINER_NAME
                for dep in dependencies
            )

            if not is_firelens_dependency_present:
                dependencies.append(firelens_dependency)
                container_def_args["DependsOn"] = dependencies

        return container_def_args

    def _sidecar_container_defs(self, configuration, service_name):
        container_definitions = []
        if configuration.get('sidecars') and isinstance(configuration['sidecars'], list):
            for index, sidecar in enumerate(configuration['sidecars']):
                container_name = sidecar.get('name', f"sidecar_{index + 1}")
                if not container_name.endswith('-sidecar'):
                    container_name = container_name + '-sidecar'
                image_uri = sidecar.get('image_uri')
                memory_reservation = int(sidecar.get('memory_reservation', 50))
                essential = sidecar.get('essential', True)
                
                
                container_def_args = {}
                command = sidecar.get('command')
                if command is not None:
                    container_def_args['Command'] = [command]
                    
                env = sidecar.get('env')
                if env is not None and isinstance(env, dict):
                    container_def_args['Environment'] = []
                    for key, value in env.items():
                        container_def_args['Environment'].append(Environment(Name=key, Value=value))
                logging = sidecar.get('logging')
                if logging is not None:
                    log_stream_prefix = service_name + f"-{container_name}"
                    log_type = "awslogs" if 'logging' not in sidecar else logging
                    container_def_args['LogConfiguration'] = self._gen_log_config(log_stream_prefix, log_type)

                health_check = sidecar.get('health_check')
                if health_check is not None and health_check.get('command') is not None:
                    health_check_args = {}
                    health_check_args['Command'] = health_check['command']
                    
                    if health_check.get('interval') is not None:
                        health_check_args['Interval'] = int(health_check['interval'])
                    if health_check.get('retries') is not None:
                        health_check_args['Retries'] = int(health_check['retries'])
                    if health_check.get('timeout') is not None:
                        health_check_args['Timeout'] = int(health_check['timeout'])

                    container_def_args['HealthCheck'] = HealthCheck(**health_check_args)
                container_definition = ContainerDefinition(
                    Name=container_name,
                    Image=image_uri,
                    MemoryReservation=memory_reservation,
                    Essential=essential,
                    **self._sidecar_firelens_overrides(configuration, container_def_args)
                )
                container_definitions.append(container_definition)
        return container_definitions
    
    def _sidecar_firelens_overrides(self, configuration, container_def_args):
        if configuration.get('logging') == 'awsfirelens':
            container_def_args['FirelensConfiguration'] = FirelensConfiguration(Type='fluentbit')
        return container_def_args

    @property
    def ecr_image_uri(self):
        return str(self.account_id) + ".dkr.ecr." + \
               self.region + ".amazonaws.com/" + \
               self.repo_name

    @property
    def account_id(self):
        return get_account_id()

    @property
    def repo_name(self):
        return self.application_name + '-repo'

    @property
    def notifications_arn(self):
        """
        Get the SNS arn either from service configuration or the cluster
        """
        if 'notifications_arn' in self.configuration:
            return self.configuration['notifications_arn']
        else:
            return TemplateGenerator.notifications_arn.fget(self)
