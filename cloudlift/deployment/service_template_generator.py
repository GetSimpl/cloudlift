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
                             PortMapping, Service, TaskDefinition)
from troposphere.elasticloadbalancingv2 import Action, Certificate, Listener
from troposphere.elasticloadbalancingv2 import LoadBalancer as ALBLoadBalancer
from troposphere.elasticloadbalancingv2 import (Matcher, RedirectConfig,
                                                TargetGroup,
                                                TargetGroupAttribute)
from troposphere.iam import Role

from cloudlift.config import region as region_service
from cloudlift.config import get_account_id
from cloudlift.config import DecimalEncoder
from cloudlift.config import get_service_stack_name
from cloudlift.deployment.deployer import build_config
from cloudlift.deployment.ecs import DeployAction, EcsClient
from cloudlift.config.logging import log, log_bold
from cloudlift.deployment.service_information_fetcher import ServiceInformationFetcher
from cloudlift.deployment.template_generator import TemplateGenerator


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

    def _derive_configuration(self, service_configuration):
        self.application_name = service_configuration.service_name
        self.configuration = service_configuration.get_config()

    def generate_service(self):
        self._add_service_parameters()
        self._add_service_outputs()
        self._fetch_current_desired_count()
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
            Threshold='80',
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

        if config['command'] is not None:
            container_definition_arguments['Command'] = [config['command']]

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

        launch_type_td = {}
        if launch_type == self.LAUNCH_TYPE_FARGATE:
            launch_type_td = {
                'RequiresCompatibilities': ['FARGATE'],
                'ExecutionRoleArn': boto3.resource('iam').Role('ecsTaskExecutionRole').arn,
                'NetworkMode': 'awsvpc',
                'Cpu': str(config['fargate']['cpu']),
                'Memory': str(config['fargate']['memory'])
            }

        td = TaskDefinition(
            service_name + "TaskDefinition",
            Family=service_name + "Family",
            ContainerDefinitions=[cd],
            TaskRoleArn=Ref(task_role),
            **launch_type_td
        )

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
                    Value=Sub("https://${" + alb.name + ".DNSName}")
                )
            )
            self.template.add_resource(svc)
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
        return LogConfiguration(
            LogDriver="awslogs",
            Options={
                'awslogs-stream-prefix': service_name,
                'awslogs-group': '-'.join([self.env, 'logs']),
                'awslogs-region': self.region
            }
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
            GroupDescription=Sub(service_name + "-alb-sg")
        )
        self.template.add_resource(svc_alb_sg)
        alb_name = service_name + pascalcase(self.env)
        if config['http_interface']['internal']:
            alb_subnets = [
                Ref(self.private_subnet1),
                Ref(self.private_subnet2)
            ]
            scheme = "internal"
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
                    {'Value': alb_name, 'Key': 'Name'}
                ],
                Scheme=scheme
            )
        else:
            alb_subnets = [
                Ref(self.public_subnet1),
                Ref(self.public_subnet2)
            ]
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
                    {'Value': alb_name, 'Key': 'Name'}
                ]
            )

        self.template.add_resource(alb)

        target_group_name = "TargetGroup" + service_name
        health_check_path = config['http_interface']['health_check_path'] if 'health_check_path' in config['http_interface'] else "/elb-check"
        if config['http_interface']['internal']:
            target_group_name = target_group_name + 'Internal'

        target_group_config = {}
        if launch_type == self.LAUNCH_TYPE_FARGATE:
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
            **target_group_config
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
