from setuptools import find_packages, setup

from version import VERSION

requirements = []
with open('requirements.txt') as f:
    requirements = f.read().splitlines()

with open("README.md", "r") as fh:
    long_description = fh.read()

setup(
    name='cloudlift',
    version=VERSION,
    packages=find_packages(),
    install_requires=requirements,
    description="Cloudlift makes it easier to launch dockerized services in AWS ECS",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/GetSimpl/cloudlift",
    zip_safe=True,
    entry_points='''
        [console_scripts]
        cloudlift=cloudlift:cli
    ''',
)
