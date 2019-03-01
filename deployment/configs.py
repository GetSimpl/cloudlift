import os

import stringcase

from deployment.logging import log_bold


def deduce_name(name):
    if name is None:
        name = os.path.basename(os.getcwd())
        log_bold("Assuming the service name to be: " + name)
    return stringcase.spinalcase(name)
