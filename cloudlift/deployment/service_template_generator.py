import json
import re

import boto3
from awacs.aws import PolicyDocument, Statement, Allow, Principal
from awacs.sts import AssumeRole
from cfn_flip import to_yaml
from stringcase import pascalcase
from troposphere import GetAtt, Output, Parameter, Ref, Sub
from troposphere.cloudwatch import Alarm, MetricDimension
from troposphere.ec2 import SecurityGroup
from troposphere.ecs import (AwsvpcConfiguration, ContainerDefinition,
                             DeploymentConfiguration, Environment,
                             LoadBalancer, LogConfiguration,
                             NetworkConfiguration, PlacementStrategy,
                             PortMapping, Service, TaskDefinition, PlacementConstraint, SystemControl,
                             HealthCheck)
from troposphere.elasticloadbalancingv2 import Action, Certificate, Listener
from troposphere.elasticloadbalancingv2 import LoadBalancer as ELBv2
from troposphere.elasticloadbalancingv2 import (Matcher, RedirectConfig,
                                                TargetGroup,
                                                TargetGroupAttribute)
from troposphere.iam import Role

from cloudlift.config import DecimalEncoder
from cloudlift.config import get_account_id
from cloudlift.deployment.deployer import build_config
from cloudlift.deployment.service_information_fetcher import ServiceInformationFetcher
from cloudlift.deployment.template_generator import TemplateGenerator


class ServiceTemplateGenerator(TemplateGenerator):
    PLACEMENT_STRATEGIES = [
        PlacementStrategy(
            Type='spread',
            Field='attribute:ecs.availability-zone'
        )]
    LAUNCH_TYPE_FARGATE = 'FARGATE'
    LAUNCH_TYPE_EC2 = 'EC2'

    def __init__(self, service_configuration, environment_stack):
        super(ServiceTemplateGenerator, self).__init__(service_configuration.environment)
        self._derive_configuration(service_configuration)
        self.env_sample_file_path = './env.sample'
        self.environment_stack = environment_stack
        information_fetcher = ServiceInformationFetcher(self.application_name, self.env)
        self.current_version = information_fetcher.get_current_version()
        self.desired_counts = information_fetcher.fetch_current_desired_count()

    def _derive_configuration(self, service_configuration):
        self.application_name = service_configuration.service_name
        self.configuration = service_configuration.get_config()

    def generate_service(self):
        self._add_service_parameters()
        self._add_service_outputs()
        self._add_ecs_service_iam_role()
        self._add_cluster_services()
        return to_yaml(self.template.to_json())

    def _add_cluster_services(self):
        for ecs_service_name, config in self.configuration['services'].items():
            self._add_service(ecs_service_name, config)

    def _add_service_alarms(self, svc):
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
            MetricName='CPUUtilization',
            TreatMissingData='breaching'
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
            Threshold='80',
            MetricName='MemoryUtilization',
            TreatMissingData='breaching'
        )
        self.template.add_resource(ecs_high_memory_alarm)
        cloudlift_timedout_deployments_alarm = Alarm(
            'FailedCloudliftDeployments' + str(svc.name),
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
            AlarmDescription='Cloudlift deployment timed out',
            Namespace='ECS/DeploymentMetrics',
            Period=60,
            ComparisonOperator='GreaterThanThreshold',
            Statistic='Average',
            Threshold='0',
            MetricName='FailedCloudliftDeployments',
            TreatMissingData='notBreaching'
        )
        self.template.add_resource(cloudlift_timedout_deployments_alarm)
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
            "Environment": [
                Environment(Name=k, Value=v) for (k, v) in env_config
            ],
            "Name": service_name + "Container",
            "Image": self.ecr_image_uri + ':' + self.current_version,
            "Essential": 'true',
            "LogConfiguration": self._gen_log_config(service_name),
            "MemoryReservation": int(config['memory_reservation']),
            "Cpu": 0
        }

        if 'http_interface' in config:
            container_definition_arguments['PortMappings'] = [
                PortMapping(
                    ContainerPort=int(
                        config['http_interface']['container_port']
                    )
                )
            ]

        if 'stop_timeout' in config:
            container_definition_arguments['StopTimeout'] = int(config['stop_timeout'])

        if 'system_controls' in config:
            container_definition_arguments['SystemControls'] = [SystemControl(Namespace=system_control['namespace'],
                                                                              Value=system_control['value']) for
                                                                system_control in config['system_controls']]

        if 'udp_interface' in config:
            container_definition_arguments['PortMappings'] = [
                PortMapping(
                    ContainerPort=int(
                        config['udp_interface']['container_port']
                    ),
                    HostPort=int(
                        config['udp_interface']['container_port']
                    ),
                    Protocol='udp'

                ),
                PortMapping(
                    ContainerPort=int(
                        config['udp_interface']['health_check_port']
                    ),
                    HostPort=int(
                        config['udp_interface']['health_check_port']
                    ),
                    Protocol='tcp'
                )
            ]
        if config['command'] is not None:
            container_definition_arguments['Command'] = [config['command']]

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
            container_definition_arguments['HealthCheck'] = HealthCheck(
                **ecs_health_check
            )

        cd = ContainerDefinition(**container_definition_arguments)

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
            )
        ))
        if 'udp_interface' in config:
            launch_type_td = {'NetworkMode': 'awsvpc'}
        else:
            launch_type_td = {}
        if launch_type == self.LAUNCH_TYPE_FARGATE:
            launch_type_td = {
                'RequiresCompatibilities': ['FARGATE'],
                'ExecutionRoleArn': boto3.resource('iam').Role('ecsTaskExecutionRole').arn,
                'NetworkMode': 'awsvpc',
                'Cpu': str(config['fargate']['cpu']),
                'Memory': str(config['fargate']['memory'])
            }

        placement_constraints = [
            PlacementConstraint(
                Type=constraint['type'], Expression=constraint['expression'])
            for constraint in config['placement_constraints']
        ] if 'placement_constraints' in config else []

        td = TaskDefinition(
            service_name + "TaskDefinition",
            Family=service_name + "Family",
            ContainerDefinitions=[cd],
            TaskRoleArn=Ref(task_role),
            PlacementConstraints=placement_constraints,
            **launch_type_td
        )

        self.template.add_resource(td)
        desired_count = self._get_desired_task_count_for_service(service_name)
        maximum_percent = config['deployment'].get('maximum_percent', 200) if 'deployment' in config else 200
        deployment_configuration = DeploymentConfiguration(MinimumHealthyPercent=100, MaximumPercent=int(maximum_percent))

        if 'udp_interface' in config:
            lb, target_group_name = self._add_ecs_lb(cd, service_name, config['udp_interface'], launch_type)
            nlb_enabled = 'nlb_enabled' in config['udp_interface'] and config['udp_interface']['nlb_enabled']
            if nlb_enabled:
                lb, service_listener, nlb_sg = self._add_alb(service_name, config, target_group_name)

            if launch_type == self.LAUNCH_TYPE_FARGATE:
                # if launch type is ec2, then services inherit the ec2 instance security group
                # otherwise, we need to specify a security group for the service
                service_security_group = SecurityGroup(
                    pascalcase("FargateService" + self.env + service_name),
                    GroupName=pascalcase("FargateService" + self.env + service_name),
                    SecurityGroupIngress=[{
                        'IpProtocol': 'UDP',
                        'SourceSecurityGroupId': Ref(nlb_sg),
                        'ToPort': int(config['udp_interface']['container_port']),
                        'FromPort': int(config['udp_interface']['container_port']),
                    },
                        {
                            'IpProtocol': 'TCP',
                            'SourceSecurityGroupId': Ref(nlb_sg),
                            'ToPort': int(config['udp_interface']['health_check_port']),
                            'FromPort': int(config['udp_interface']['health_check_port']),
                        }
                    ],
                    VpcId=Ref(self.vpc),
                    GroupDescription=pascalcase("FargateService" + self.env + service_name)
                )
                self.template.add_resource(service_security_group)
            else:
                service_security_group = nlb_sg

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
            if launch_type == self.LAUNCH_TYPE_EC2:
                launch_type_svc['PlacementStrategies'] = self.PLACEMENT_STRATEGIES
            svc = Service(
                service_name,
                LoadBalancers=[lb],
                Cluster=self.cluster_name,
                TaskDefinition=Ref(td),
                DesiredCount=desired_count,
                DependsOn=service_listener.title,
                LaunchType=launch_type,
                **launch_type_svc,
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
                    Value=Sub("udp://${" + lb.name + ".DNSName}")
                )
            )
            self.template.add_resource(svc)
        elif 'http_interface' in config:
            lb, target_group_name = self._add_ecs_lb(cd, service_name, config['http_interface'], launch_type)
            alb_enabled = 'alb_enabled' in config['http_interface'] and config['http_interface']['alb_enabled']
            if alb_enabled:
                lb, service_listener, alb_sg = self._add_alb(service_name, config, target_group_name)

            if launch_type == self.LAUNCH_TYPE_FARGATE:
                # if launch type is ec2, then services inherit the ec2 instance security group
                # otherwise, we need to specify a security group for the service
                security_group_ingress = {
                    'IpProtocol': 'TCP',
                    'ToPort': int(config['http_interface']['container_port']),
                    'FromPort': int(config['http_interface']['container_port']),
                }
                if alb_enabled:
                    security_group_ingress['SourceSecurityGroupId'] = Ref(alb_sg)

                service_security_group = SecurityGroup(
                    pascalcase("FargateService" + self.env + service_name),
                    GroupName=pascalcase("FargateService" + self.env + service_name),
                    SecurityGroupIngress=[security_group_ingress],
                    VpcId=Ref(self.vpc),
                    GroupDescription=pascalcase("FargateService" + self.env + service_name)
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
                launch_type_svc = {
                    'Role': Ref(self.ecs_service_role),
                    'PlacementStrategies': self.PLACEMENT_STRATEGIES
                }

            if alb_enabled:
                launch_type_svc['DependsOn'] = service_listener.title
            svc = Service(
                service_name,
                LoadBalancers=[lb],
                Cluster=self.cluster_name,
                TaskDefinition=Ref(td),
                DesiredCount=desired_count,
                DeploymentConfiguration=deployment_configuration,
                LaunchType=launch_type,
                **launch_type_svc,
            )

            self.template.add_output(
                Output(
                    service_name + 'EcsServiceName',
                    Description='The ECS name which needs to be entered',
                    Value=GetAtt(svc, 'Name')
                )
            )

            self.template.add_resource(svc)

            if alb_enabled:
                self.template.add_output(
                    Output(
                        service_name + "URL",
                        Description="The URL at which the service is accessible",
                        Value=Sub("https://${" + lb.name + ".DNSName}")
                    )
                )
        else:
            launch_type_svc = {}
            if launch_type == self.LAUNCH_TYPE_FARGATE:
                # if launch type is ec2, then services inherit the ec2 instance security group
                # otherwise, we need to specify a security group for the service
                service_security_group = SecurityGroup(
                    pascalcase("FargateService" + self.env + service_name),
                    GroupName=pascalcase("FargateService" + self.env + service_name),
                    SecurityGroupIngress=[],
                    VpcId=Ref(self.vpc),
                    GroupDescription=pascalcase("FargateService" + self.env + service_name)
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
                **launch_type_svc
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

    def _gen_log_config(self, service_name):
        current_service_config = self.configuration['services'][service_name]
        env_log_group = '-'.join([self.env, 'logs'])
        return LogConfiguration(
            LogDriver="awslogs",
            Options={
                'awslogs-stream-prefix': service_name,
                'awslogs-group': current_service_config.get('log_group', env_log_group),
                'awslogs-region': self.region
            }
        )

    def _add_ecs_lb(self, cd, service_name, elb_config, launch_type):
        target_group_name = "TargetGroup" + service_name
        health_check_path = elb_config['health_check_path'] if 'health_check_path' in elb_config else "/elb-check"
        if elb_config['internal']:
            target_group_name = target_group_name + 'Internal'

        target_group_config = {}
        if launch_type == self.LAUNCH_TYPE_FARGATE:
            target_group_config['TargetType'] = 'ip'
        if protocol == 'http':
            target_group_config['Matcher'] = Matcher(HttpCode="200-399")
            target_group_config['HealthCheckPath'] = health_check_path
            target_group_config['Port'] = int(elb_config['container_port'])
        elif protocol == 'udp':
            target_group_config['Port'] = int(elb_config['container_port'])
            target_group_config['HealthCheckPort'] = int(elb_config['health_check_port'])
            target_group_config['TargetType'] = 'ip'
        service_target_group = TargetGroup(
            target_group_name,
            HealthyThresholdCount=2,
            HealthCheckIntervalSeconds=30,
            TargetGroupAttributes=[
                TargetGroupAttribute(
                    Key='deregistration_delay.timeout_seconds',
                    Value='30'
                )
            ],
            VpcId=Ref(self.vpc),
            Protocol=protocol.upper(),
            HealthCheckTimeoutSeconds=10,
            UnhealthyThresholdCount=3,
            **target_group_config
        )

        self.template.add_resource(service_target_group)

        lb = LoadBalancer(
            ContainerName=cd.Name,
            TargetGroupArn=Ref(service_target_group),
            ContainerPort=int(elb_config['container_port'])
        )

        return lb, target_group_name

    def _add_alb(self, service_name, config, target_group_name):
        sg_name = 'SG' + self.env + service_name
        protocol = 'http' if 'http_interface' in config else 'udp'
        elb_config = config[f'{protocol}_interface']
        svc_alb_sg = SecurityGroup(
            re.sub(r'\W+', '', sg_name),
            GroupName=self.env + '-' + service_name,
            SecurityGroupIngress=self._generate_alb_security_group_ingress(
                elb_config, protocol),
            VpcId=Ref(self.vpc),
            GroupDescription=Sub(service_name + "-alb-sg")
        )
        self.template.add_resource(svc_alb_sg)

        alb_name = service_name + pascalcase(self.env)
        if elb_config['internal']:
            alb_subnets = [
                Ref(self.private_subnet1),
                Ref(self.private_subnet2)
            ]
            scheme = "internal"
            alb_name += 'Internal'
        else:
            scheme = 'internet-facing'
            alb_subnets = [
                Ref(self.public_subnet1),
                Ref(self.public_subnet2)
            ]
        alb_name = alb_name[:32]
        elb = ELBv2(
            'ALB' + service_name,
            Subnets=alb_subnets,
            SecurityGroups=[
                self.alb_security_group,
                Ref(svc_alb_sg)
            ] if protocol == 'http' else [],
            Name=alb_name,
            Tags=[
                {'Value': alb_name, 'Key': 'Name'}
            ],
            Scheme=scheme,
            Type='application' if 'http_interface' in config else 'network'
        )

        self.template.add_resource(elb)

        target_group_action = Action(
            TargetGroupArn=Ref(target_group_name),
            Type="forward"
        )

        if protocol == 'http':
            service_listener = self._add_service_listener(
                service_name,
                target_group_action,
                elb,
                elb_config['internal']
            )
        elif protocol == 'udp':
            service_listener = Listener(
                "LoadBalancerListener" + service_name,
                Protocol="UDP",
                DefaultActions=[target_group_action],
                LoadBalancerArn=Ref(elb),
                Port=int(config['udp_interface']['container_port']),
            )
            self.template.add_resource(service_listener)

        self._add_elb_alarms(service_name, elb)
        return elb, service_listener, svc_alb_sg

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

    def _add_elb_alarms(self, service_name, elb_v2):
        unhealthy_alarm = Alarm(
            'ElbUnhealthyHostAlarm' + service_name,
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(
                    Name='LoadBalancer',
                    Value=GetAtt(elb_v2, 'LoadBalancerFullName')
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
                    Value=GetAtt(elb_v2, 'LoadBalancerFullName')
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
                    Value=GetAtt(elb_v2, 'LoadBalancerFullName')
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

    def _generate_alb_security_group_ingress(self, config, protocol='http'):
        ingress_rules = []
        for access_ip in config['restrict_access_to']:
            if access_ip.find('/') == -1:
                access_ip = access_ip + '/32'
            if protocol == 'http':
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
            else:
                port = config['container_port']
                health_check_port = config['health_check_port']
                ingress_rules.append({
                    'ToPort': int(port),
                    'IpProtocol': 'UDP',
                    'FromPort': int(port),
                    'CidrIp': access_ip
                })
                ingress_rules.append(
                    {
                        'ToPort': int(health_check_port),
                        'IpProtocol': 'TCP',
                        'FromPort': int(health_check_port),
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

    def _get_desired_task_count_for_service(self, service_name):
        if service_name in self.desired_counts:
            return self.desired_counts[service_name]
        else:
            return 0

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
