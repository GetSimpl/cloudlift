LAUNCH_TYPE_FARGATE = 'FARGATE'
LAUNCH_TYPE_EC2 = 'EC2'


def get_launch_type(ecs_service_configuration):
    return LAUNCH_TYPE_FARGATE if 'fargate' in ecs_service_configuration \
        else LAUNCH_TYPE_EC2
