from os import path, getcwd

import stringcase

from cloudlift.config.logging import log_bold


def deduce_name(name):
    if name is None:
        name = path.basename(getcwd())
        log_bold("Assuming the service name to be: " + name)
    return stringcase.spinalcase(name)
