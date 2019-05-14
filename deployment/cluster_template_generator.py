import json
import re

from cfn_flip import to_yaml
from stringcase import camelcase, pascalcase
from troposphere import (Base64, FindInMap, Output, Parameter, Ref, Sub,
                         cloudformation)
from troposphere.autoscaling import (AutoScalingGroup, LaunchConfiguration,
                                     ScalingPolicy)
from troposphere.cloudwatch import Alarm, MetricDimension
from troposphere.ec2 import (VPC, InternetGateway, NatGateway, Route,
                             RouteTable, SecurityGroup, Subnet,
                             SubnetRouteTableAssociation, VPCGatewayAttachment)
from troposphere.ecs import Cluster
from troposphere.elasticache import SubnetGroup as ElastiCacheSubnetGroup
from troposphere.iam import InstanceProfile, Role
from troposphere.logs import LogGroup
from troposphere.policies import (AutoScalingRollingUpdate, CreationPolicy,
                                  ResourceSignal)
from troposphere.rds import DBSubnetGroup

from config.decimal_encoder import DecimalEncoder
from config.region import get_client_for, get_region_for_environment
from deployment.template_generator import TemplateGenerator
from version import VERSION


class ClusterTemplateGenerator(TemplateGenerator):
    """
        This class generates CloudFormation template for a environment cluster
    """

    def __init__(self, environment, environment_configuration, desired_instances=None):
        super(ClusterTemplateGenerator, self).__init__(environment)
        self.configuration = environment_configuration
        if desired_instances is None:
            self.desired_instances = self.configuration['cluster']['min_instances']
        else:
            self.desired_instances = desired_instances
        self.private_subnets = []
        self.public_subnets = []
        self._get_availability_zones()

    def generate_cluster(self):
        self.__validate_parameters()
        self._setup_network(
            self.configuration['vpc']['cidr'],
            self.configuration['vpc']['subnets'],
            self.configuration['vpc']['nat-gateway']['elastic-ip-allocation-id'],
        )
        self._create_log_group()
        self._add_cluster_outputs()
        self._add_cluster_parameters()
        self._add_mappings()
        self._add_metadata()
        self._add_cluster()
        return to_yaml(json.dumps(self.template.to_dict(), cls=DecimalEncoder))

    def _get_availability_zones(self):
        client = get_client_for('ec2', self.env)
        aws_azs = client.describe_availability_zones()['AvailabilityZones']
        self.availability_zones = [
            zone['ZoneName'] for zone in aws_azs
        ][:2]

    def __validate_parameters(self):
        # TODO validate CIDR
        # TODO
        return False

    # TODO: clean up
    def _setup_network(self, cidr_block, subnet_configs, eip_allocation_id):
        self._create_vpc(cidr_block)
        self._create_public_network(subnet_configs['public'])
        self._create_private_network(
            subnet_configs['private'],
            eip_allocation_id
        )
        self._create_database_subnet_group()

    def _create_vpc(self, cidr_block):
        self.vpc = VPC(
            camelcase("{self.env}Vpc".format(**locals())),
            CidrBlock=cidr_block,
            EnableDnsSupport=True,
            EnableDnsHostnames=True,
            InstanceTenancy='default',
            Tags=[
                {'Key': 'category', 'Value': 'services'},
                {'Key': 'environment', 'Value': self.env},
                {'Key': 'Name', 'Value': "{self.env}-vpc".format(**locals())}]
        )
        self.template.add_resource(self.vpc)
        self.internet_gateway = InternetGateway(
            camelcase("{self.env}Ig".format(**locals())),
            Tags=[
                {
                    'Key': 'Name',
                    'Value': "{self.env}-internet-gateway".format(**locals())
                },
                {'Key': 'environment', 'Value': self.env}
            ]
        )
        self.template.add_resource(self.internet_gateway)
        vpc_gateway_attachment = VPCGatewayAttachment(
            camelcase("{self.env}Attachment".format(**locals())),
            InternetGatewayId=Ref(self.internet_gateway),
            VpcId=Ref(self.vpc)
        )
        self.template.add_resource(vpc_gateway_attachment)
        return None

    def _create_public_network(self, subnet_configs):
        public_route_table = RouteTable(
            camelcase("{self.env}Public".format(**locals())),
            VpcId=Ref(self.vpc),
            Tags=[
                {
                    'Key': 'Name',
                    'Value': "{self.env}-public".format(**locals())
                },
                {'Key': 'environment', 'Value': self.env}
            ],
            DependsOn=self.vpc.title)
        self.template.add_resource(public_route_table)
        subnet_count = 0
        for subnet_title, subnet_config in subnet_configs.items():
            subnet_count += 1
            if subnet_count % 2 == 0:
                availability_zone = self.availability_zones[0]
            else:
                availability_zone = self.availability_zones[1]

            subnet_title = camelcase("{self.env}Public".format(**locals())) + \
                pascalcase(re.sub('[^a-zA-Z0-9*]', '', subnet_title))
            subnet_name = "{self.env}-public-{subnet_count}".format(**locals())
            subnet = Subnet(
                subnet_title,
                AvailabilityZone=availability_zone,
                CidrBlock=subnet_config['cidr'],
                VpcId=Ref(self.vpc),
                MapPublicIpOnLaunch=True,
                Tags=[
                    {'Key': 'Name', 'Value': subnet_name},
                    {'Key': 'environment', 'Value': self.env}
                ]
            )
            self.public_subnets.append(subnet)
            self.template.add_resource(subnet)
            subnet_route_table_association = SubnetRouteTableAssociation(
                camelcase("{self.env}PublicSubnet{subnet_count}Assoc".format(**locals())),
                RouteTableId=Ref(public_route_table),
                SubnetId=Ref(subnet)
            )
            self.template.add_resource(subnet_route_table_association)

        internet_gateway_route = Route(
            camelcase("{self.env}IgRoute".format(**locals())),
            DestinationCidrBlock='0.0.0.0/0',
            GatewayId=Ref(self.internet_gateway),
            RouteTableId=Ref(public_route_table)
        )
        self.template.add_resource(internet_gateway_route)
        return None

    def _create_private_network(self, subnet_configs, eip_allocation_id):
        private_route_table = RouteTable(
            camelcase("{self.env}Private".format(**locals())),
            VpcId=Ref(self.vpc),
            Tags=[
                {
                    'Key': 'Name',
                    'Value': "{self.env}-private".format(**locals())
                },
                {'Key': 'environment', 'Value': self.env}
            ]
        )
        self.template.add_resource(private_route_table)
        subnet_count = 0
        for subnet_title, subnet_config in subnet_configs.items():
            subnet_count += 1
            if subnet_count % 2 == 0:
                availability_zone = self.availability_zones[0]
            else:
                availability_zone = self.availability_zones[1]
            subnet_title = camelcase("{self.env}Private".format(**locals())) + \
                pascalcase(re.sub('[^a-zA-Z0-9*]', '', subnet_title))
            subnet_name = "{self.env}-private-{subnet_count}".format(**locals())
            subnet = Subnet(
                subnet_title,
                AvailabilityZone=availability_zone,
                CidrBlock=subnet_config['cidr'],
                VpcId=Ref(self.vpc),
                MapPublicIpOnLaunch=False,
                Tags=[
                    {'Key': 'Name', 'Value': subnet_name},
                    {'Key': 'environment', 'Value': self.env}
                ]
            )
            self.private_subnets.append(subnet)
            self.template.add_resource(subnet)
            subnet_route_table_association = SubnetRouteTableAssociation(
                camelcase("{self.env}PrivateSubnet{subnet_count}Assoc".format(
                    **locals())),
                RouteTableId=Ref(private_route_table),
                SubnetId=Ref(subnet)
            )
            self.template.add_resource(subnet_route_table_association)

        nat_gateway = NatGateway(
            camelcase("{self.env}Nat".format(**locals())),
            AllocationId=eip_allocation_id,
            SubnetId=Ref(self.public_subnets[0]),
            Tags=[
                {
                    'Key': 'Name',
                    'Value': "{self.env}-nat-gateway".format(**locals())
                },
                {'Key': 'environment', 'Value': self.env}
            ]
        )
        self.template.add_resource(nat_gateway)
        nat_gateway_route = Route(
            camelcase("{self.env}NatRoute".format(**locals())),
            DestinationCidrBlock='0.0.0.0/0',
            NatGatewayId=Ref(nat_gateway),
            RouteTableId=Ref(private_route_table)
        )
        self.template.add_resource(nat_gateway_route)
        return None

    def _create_database_subnet_group(self):
        database_subnet_group = DBSubnetGroup(
            "DBSubnetGroup",
            DBSubnetGroupName="{self.env}-subnet".format(**locals()),
            Tags=[
                {'Key': 'category', 'Value': 'services'},
                {'Key': 'environment', 'Value': self.env}
            ],
            DBSubnetGroupDescription="{self.env} subnet group".format(
                **locals()),
            SubnetIds=[Ref(subnet) for subnet in self.private_subnets]
        )
        self.template.add_resource(database_subnet_group)
        elasticache_subnet_group = ElastiCacheSubnetGroup(
            "ElasticacheSubnetGroup",
            CacheSubnetGroupName="{self.env}-subnet".format(**locals()),
            Description="{self.env} subnet group".format(**locals()),
            SubnetIds=[Ref(subnet) for subnet in self.private_subnets]
        )
        self.template.add_resource(elasticache_subnet_group)

    def _create_log_group(self):
        log_group = LogGroup(
            camelcase("{self.env}LogGroup".format(**locals())),
            LogGroupName="{self.env}-logs".format(**locals()),
            RetentionInDays=365
        )
        self.template.add_resource(log_group)
        return None

    def _create_notification_sns(self):
        return None

    def _add_instance_profile(self):
        role_name = Sub('ecs-${AWS::StackName}-${AWS::Region}')
        assume_role_policy = {
            u'Statement': [
                {
                    u'Action': [
                        u'sts:AssumeRole'
                    ],
                    u'Effect': u'Allow',
                    u'Principal': {
                        u'Service': [
                            u'ec2.amazonaws.com'
                        ]
                    }
                }
            ]
        }
        ecs_role = Role(
            'ECSRole',
            Path='/',
            ManagedPolicyArns=[
                'arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role',
                'arn:aws:iam::aws:policy/AmazonDynamoDBReadOnlyAccess',
                'arn:aws:iam::aws:policy/service-role/AmazonEC2RoleforSSM'
            ],
            RoleName=role_name,
            AssumeRolePolicyDocument=assume_role_policy
        )
        self.template.add_resource(ecs_role)
        instance_profile = InstanceProfile(
            "InstanceProfile",
            Path='/',
            Roles=[
                Ref(ecs_role)
            ]
        )
        self.template.add_resource(instance_profile)
        return instance_profile

    def _add_cluster(self):
        cluster = Cluster('Cluster', ClusterName=Ref('AWS::StackName'))
        self.template.add_resource(cluster)
        self._add_ec2_auto_scaling()
        self._add_cluster_alarms(cluster)
        return cluster

    def _add_cluster_alarms(self, cluster):
        ec2_hosts_high_cpu_alarm = Alarm(
            'Ec2HostsHighCPUAlarm',
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(Name='AutoScalingGroupName',
                                Value=Ref(self.auto_scaling_group))
            ],
            AlarmActions=[Ref(self.notification_sns_arn)],
            AlarmDescription='Alarm if CPU too high or metric disappears \
indicating instance is down',
            Namespace='AWS/EC2',
            Period=60,
            ComparisonOperator='GreaterThanThreshold',
            Statistic='Average',
            Threshold='60',
            MetricName='CPUUtilization'
        )
        self.template.add_resource(ec2_hosts_high_cpu_alarm)
        cluster_high_cpu_alarm = Alarm(
            'ClusterHighCPUAlarm',
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(Name='ClusterName', Value=Ref(cluster))
            ],
            AlarmActions=[
                Ref(self.notification_sns_arn)
            ],
            AlarmDescription='Alarm if CPU is too high for cluster.',
            Namespace='AWS/ECS',
            Period=300,
            ComparisonOperator='GreaterThanThreshold',
            Statistic='Average',
            Threshold='60',
            MetricName='CPUUtilization'
        )
        self.template.add_resource(cluster_high_cpu_alarm)
        cluster_high_memory_alarm = Alarm(
            'ClusterHighMemoryAlarm',
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(Name='ClusterName', Value=Ref(cluster))
            ],
            AlarmActions=[
                Ref(self.notification_sns_arn)
            ],
            AlarmDescription='Alarm if memory is too high for cluster.',
            Namespace='AWS/ECS',
            Period=300,
            ComparisonOperator='GreaterThanThreshold',
            Statistic='Average',
            Threshold='60',
            MetricName='MemoryUtilization'
        )
        self.template.add_resource(cluster_high_memory_alarm)
        self.cluster_high_memory_reservation_autoscale_alarm = Alarm(
            'ClusterHighMemoryReservationAlarm',
            EvaluationPeriods=1,
            Dimensions=[
                MetricDimension(Name='ClusterName', Value=Ref(cluster))
            ],
            AlarmActions=[
                Ref(self.cluster_scaling_policy)
            ],
            AlarmDescription='Alarm if memory reservation is over 75% \
for cluster.',
            Namespace='AWS/ECS',
            Period=300,
            ComparisonOperator='GreaterThanThreshold',
            Statistic='Average',
            Threshold='75',
            MetricName='MemoryReservation'
        )
        self.template.add_resource(
            self.cluster_high_memory_reservation_autoscale_alarm)
        self.cluster_high_memory_reservation_user_notification_alarm = Alarm(
            'ClusterHighMemoryReservationUserNotifcationAlarm',
            EvaluationPeriods=3,
            Dimensions=[
                MetricDimension(Name='ClusterName', Value=Ref(cluster))
            ],
            AlarmActions=[
                Ref(self.notification_sns_arn)
            ],
            OKActions=[
                Ref(self.notification_sns_arn)
            ],
            AlarmDescription='Alarm if memory reservation is over 75% \
for cluster for 15 minutes.',
            Namespace='AWS/ECS',
            Period=300,
            ComparisonOperator='GreaterThanThreshold',
            Statistic='Average',
            Threshold='75',
            MetricName='MemoryReservation'
        )
        self.template.add_resource(
            self.cluster_high_memory_reservation_user_notification_alarm)

    def _add_ec2_auto_scaling(self):
        instance_profile = self._add_instance_profile()
        self.sg_alb = SecurityGroup(
            "SecurityGroupAlb",
            VpcId=Ref(self.vpc),
            GroupDescription=Sub("${AWS::StackName}-alb")
        )
        self.template.add_resource(self.sg_alb)
        sg_hosts = SecurityGroup(
            "SecurityGroupEc2Hosts",
            SecurityGroupIngress=[
                {
                    'SourceSecurityGroupId': Ref(self.sg_alb),
                    'IpProtocol': -1
                }
            ],
            VpcId=Ref(self.vpc),
            GroupDescription=Sub("${AWS::StackName}-hosts")
        )
        self.template.add_resource(sg_hosts)
        database_security_group = SecurityGroup(
            "SecurityGroupDatabases",
            SecurityGroupIngress=[
                {
                    'SourceSecurityGroupId': Ref(sg_hosts),
                    'IpProtocol': -1
                }
            ],
            VpcId=Ref(self.vpc),
            GroupDescription=Sub("${AWS::StackName}-databases")
        )
        self.template.add_resource(database_security_group)
        user_data = Base64(Sub('\n'.join([
            "#!/bin/bash",
            "yum install -y aws-cfn-bootstrap",
            "/opt/aws/bin/cfn-init -v --region ${AWS::Region} --stack ${AWS::StackName} --resource LaunchConfiguration",
            "/opt/aws/bin/cfn-signal -e $? --region ${AWS::Region} --stack ${AWS::StackName} --resource AutoScalingGroup",
            "yum install -y https://s3.amazonaws.com/ec2-downloads-windows/SSMAgent/latest/linux_amd64/amazon-ssm-agent.rpm",
            "systemctl enable amazon-ssm-agent",
            "systemctl start amazon-ssm-agent",
            ""])))
        lc_metadata = cloudformation.Init({
            "config": cloudformation.InitConfig(
                files=cloudformation.InitFiles({
                    "/etc/cfn/cfn-hup.conf": cloudformation.InitFile(
                        content=Sub(
                            '\n'.join([
                                    '[main]',
                                    'stack=${AWS::StackId}',
                                    'region=${AWS::Region}',
                                    ''
                                ])
                            ),
                        mode='256',  # TODO: Why 256
                        owner="root",
                        group="root"
                    ),
                    "/etc/cfn/hooks.d/cfn-auto-reloader.conf": cloudformation.InitFile(
                        content=Sub(
                            '\n'.join([
                                '[cfn-auto-reloader-hook]',
                                'triggers=post.update',
                                'path=Resources.ContainerInstances.Metadata.AWS::CloudFormation::Init',
                                'action=/opt/aws/bin/cfn-init -v --region ${AWS::Region} --stack ${AWS::StackName} --resource LaunchConfiguration',
                                ''
                            ])
                        ),
                    )
                }),
                services={
                    "sysvinit": cloudformation.InitServices({
                        "cfn-hup": cloudformation.InitService(
                            enabled=True,
                            ensureRunning=True,
                            files=['/etc/cfn/cfn-hup.conf',
                                   '/etc/cfn/hooks.d/cfn-auto-reloader.conf']
                        )
                    })
                },
                commands={
                    '01_add_instance_to_cluster': {
                        'command': Sub(
                            'echo ECS_CLUSTER=${Cluster} > /etc/ecs/ecs.config'
                        )
                    }
                }
            )
        })
        launch_configuration = LaunchConfiguration(
            'LaunchConfiguration',
            UserData=user_data,
            IamInstanceProfile=Ref(instance_profile),
            SecurityGroups=[Ref(sg_hosts)],
            InstanceType=Ref('InstanceType'),
            ImageId=FindInMap("AWSRegionToAMI", Ref("AWS::Region"), "AMI"),
            Metadata=lc_metadata,
            KeyName=Ref(self.key_pair)
        )
        self.template.add_resource(launch_configuration)
        # , PauseTime='PT15M', WaitOnResourceSignals=True, MaxBatchSize=1, MinInstancesInService=1)
        up = AutoScalingRollingUpdate('AutoScalingRollingUpdate')
        # TODO: clean up
        subnets = list(self.private_subnets)
        self.auto_scaling_group = AutoScalingGroup(
            "AutoScalingGroup",
            UpdatePolicy=up,
            DesiredCapacity=self.desired_instances,
            Tags=[
                {
                    'PropagateAtLaunch': True,
                    'Value': Sub('${AWS::StackName} - ECS Host'),
                    'Key': 'Name'
                }
            ],
            MinSize=Ref('MinSize'),
            MaxSize=Ref('MaxSize'),
            VPCZoneIdentifier=[Ref(subnets.pop()), Ref(subnets.pop())],
            LaunchConfigurationName=Ref(launch_configuration),
            CreationPolicy=CreationPolicy(
                ResourceSignal=ResourceSignal(Timeout='PT15M')
            )
        )
        self.template.add_resource(self.auto_scaling_group)
        self.cluster_scaling_policy = ScalingPolicy(
            'AutoScalingPolicy',
            AdjustmentType='ChangeInCapacity',
            AutoScalingGroupName=Ref(self.auto_scaling_group),
            Cooldown=300,
            PolicyType='SimpleScaling',
            ScalingAdjustment=1
        )
        self.template.add_resource(self.cluster_scaling_policy)

    def _add_cluster_parameters(self):
        self.template.add_parameter(Parameter(
            "Environment",
            Description='',
            Type="String",
            Default="")
        )
        self.key_pair = Parameter(
            "KeyPair", Description='', Type="AWS::EC2::KeyPair::KeyName", Default="")
        self.template.add_parameter(self.key_pair)
        self.template.add_parameter(Parameter(
            "MinSize", Description='', Type="Number", Default=str(self.configuration['cluster']['min_instances'])))
        self.template.add_parameter(Parameter(
            "MaxSize", Description='', Type="Number", Default=str(self.configuration['cluster']['max_instances'])))
        self.notification_sns_arn = Parameter("NotificationSnsArn",
                                              Description='',
                                              Type="String",
                                              Default=self.notifications_arn)
        self.template.add_parameter(self.notification_sns_arn)
        self.template.add_parameter(Parameter(
            "InstanceType", Description='', Type="String", Default=self.configuration['cluster']['instance_type']))

    def _add_mappings(self):
        # Pick from https://docs.aws.amazon.com/AmazonECS/latest/developerguide/al2ami.html
        ssm_client = get_client_for('ssm', self.env)
        ami_response = ssm_client.get_parameter(
            Name='/aws/service/ecs/optimized-ami/amazon-linux-2/recommended')
        ami_id = json.loads(ami_response['Parameter']['Value'])['image_id']
        region = get_region_for_environment(self.env)
        self.template.add_mapping('AWSRegionToAMI', {
            region: {"AMI": ami_id}
        })

    def _add_cluster_outputs(self):
        self._add_stack_outputs()
        metadata = {
            'env': self.env,
            'min_instances': str(self.configuration['cluster']['min_instances']),
            'max_instances': str(self.configuration['cluster']['max_instances']),
            'instance_type': self.configuration['cluster']['instance_type'],
            'key_name': self.configuration['cluster']['key_name'],
            'cloudlift_version': VERSION
        }
        self.template.add_output(Output(
            "CloudliftOptions",
            Description="Options used with cloudlift when building this cluster",
            Value=json.dumps(metadata))
        )
        self.template.add_output(Output(
            "VPC",
            Description="VPC in which environment is setup",
            Value=Ref(self.vpc))
        )
        private_subnets = list(self.private_subnets)
        self.template.add_output(Output(
            "PrivateSubnet1",
            Description="ID of the 1st subnet",
            Value=Ref(private_subnets.pop()))
        )
        self.template.add_output(Output(
            "PrivateSubnet2",
            Description="ID of the 2nd subnet",
            Value=Ref(private_subnets.pop()))
        )
        public_subnets = list(self.public_subnets)
        self.template.add_output(Output(
            "PublicSubnet1",
            Description="ID of the 1st subnet",
            Value=Ref(public_subnets.pop()))
        )
        self.template.add_output(Output(
            "PublicSubnet2",
            Description="ID of the 2nd subnet",
            Value=Ref(public_subnets.pop()))
        )
        self.template.add_output(Output(
            "AutoScalingGroup",
            Description="AutoScaling group for ECS container instances",
            Value=Ref('AutoScalingGroup'))
        )
        self.template.add_output(Output(
            "SecurityGroupAlb",
            Description="Security group ID for ALB",
            Value=Ref('SecurityGroupAlb'))
        )
        self.template.add_output(Output(
            "MinInstances",
            Description="Minimum instances in cluster",
            Value=str(self.configuration['cluster']['min_instances']))
        )
        self.template.add_output(Output(
            "MaxInstances",
            Description="Maximum instances in cluster",
            Value=str(self.configuration['cluster']['max_instances']))
        )
        self.template.add_output(Output(
            "InstanceType",
            Description="EC2 instance type",
            Value=str(self.configuration['cluster']['instance_type']))
        )
        self.template.add_output(Output(
            "KeyName",
            Description="Key Pair name for accessing the instances",
            Value=str(self.configuration['cluster']['key_name']))
        )

    def _add_metadata(self):
        self.template.add_metadata({
            'AWS::CloudFormation::Interface': {
                'ParameterGroups': [
                    {
                        'Label': {
                            'default': 'Cluster Configuration'
                        },
                        'Parameters': [
                            'KeyPair',
                            'Environment',
                            'MinSize',
                            'MaxSize',
                            'InstanceType',
                            'VPC',
                            'Subnet1',
                            'Subnet2',
                            'NotificationSnsArn'
                        ]
                    },
                ],
                'ParameterLabels': {
                    'Environment': {
                        'default': 'Enter the environment e.g. dev or staging or sandbox or production'
                    },
                    'InstanceType': {
                        'default': 'Type of instance'
                    },
                    'KeyPair': {
                        'default': 'Select the key with which you want to login to the ec2 instances'},
                    'MaxSize': {
                        'default': 'Max. no. of instances in cluster'
                    },
                    'MinSize': {
                        'default': 'Min. no. of instances in cluster'
                    },
                    'NotificationSnsArn': {
                        'default': 'The SNS topic to which notifactions has to be triggered'
                    },
                    'Subnet1': {
                        'default': 'Enter the ID of the 1st subnet'
                    },
                    'Subnet2': {
                        'default': 'Enter the ID of the 2nd subnet'
                    },
                    'VPC': {
                        'default': 'Enter the VPC in which you want the environment to be setup'
                    },
                }
            }
        })
