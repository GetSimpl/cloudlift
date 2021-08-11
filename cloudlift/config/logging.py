import click


def log_err(text):
    click.secho(text, fg='red', bold=True, err=True)

def log(text):
    click.secho(text, fg='green', err=True)

def log_warning(text):
    click.secho(text, fg='yellow', err=True)

def log_bold(text):
    click.secho(text, fg='green',  bold=True, err=True)

def log_intent(text, level=1):
    click.secho(''.join(['  '] * level + [text]), fg='green', err=True)

def log_intent_err(text, level=1):
    click.secho(''.join(['  '] * level + [text]), fg='red', err=True)

def log_with_color(text, color, level=2):
    click.secho(''.join(['  '] * level + [text]), fg=color, err=True)
