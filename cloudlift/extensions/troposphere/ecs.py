from troposphere import AWSObject, Tags, AWSProperty
from troposphere.ecs import ContainerDefinition, InferenceAccelerator, PlacementConstraint, ProxyConfiguration, \
    DockerVolumeConfiguration, Host


class EfsVolumeConfiguration(AWSProperty):
    props = {
        'FileSystemId': (str, True),
        'TransitEncryption': (str, True)
    }


class Volume(AWSProperty):
    props = {
        'DockerVolumeConfiguration': (DockerVolumeConfiguration, False),
        'EfsVolumeConfiguration': (EfsVolumeConfiguration, False),
        'Name': (str, True),
        'Host': (Host, False),
    }


class TaskDefinition(AWSObject):
    resource_type = "AWS::ECS::TaskDefinition"

    props = {
        'ContainerDefinitions': ([ContainerDefinition], False),
        'Cpu': (str, False),
        'ExecutionRoleArn': (str, False),
        'Family': (str, False),
        'InferenceAccelerators': ([InferenceAccelerator], False),
        'IpcMode': (str, False),
        'Memory': (str, False),
        'NetworkMode': (str, False),
        'PidMode': (str, False),
        'PlacementConstraints': ([PlacementConstraint], False),
        'ProxyConfiguration': (ProxyConfiguration, False),
        'RequiresCompatibilities': ([str], False),
        'Tags': (Tags, False),
        'TaskRoleArn': (str, False),
        'Volumes': ([Volume], False),
    }
