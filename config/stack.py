# TODO: Simpl
def get_cluster_name(environment):
    if environment == 'unicorn':
        environment_name = environment + "-cluster"
    else:
        environment_name = "cluster-" + environment
    return environment_name


def get_service_stack_name(environment, name):
    if environment == 'unicorn':
        stack_name = '-'.join([environment, name])
    else:
        stack_name = '-'.join([name, environment])
    return stack_name
