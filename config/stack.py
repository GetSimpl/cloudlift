def get_cluster_name(environment):
    return "cluster-" + environment


def get_service_stack_name(environment, name):
    return '-'.join([name, environment])
