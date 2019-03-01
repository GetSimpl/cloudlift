import click

from deployment.logging import log_warning


def highlight_production():
    print('''\033[91m
********************************
**          Careful!          **
**    You're on PRODUCTION    **
********************************\033[0m
''')
