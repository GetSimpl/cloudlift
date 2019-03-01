import click


def log_err(text):
    click.secho(text, fg='red', bold=True)

def log(text):
    click.secho(text, fg='green')

def log_warning(text):
    click.secho(text, fg='yellow')

def log_bold(text):
    click.secho(text, fg='green',  bold=True)

def log_intent(text, level=1):
    click.secho(''.join(['  '] * level + [text]), fg='green')

def log_intent_err(text, level=1):
    click.secho(''.join(['  '] * level + [text]), fg='red')

def log_with_color(text, color, level=2):
    click.secho(''.join(['  '] * level + [text]), fg=color)
