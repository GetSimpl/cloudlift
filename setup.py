from setuptools import setup, find_packages
from version import VERSION

requirements = []
with open('requirements.txt') as f:
    requirements = f.read().splitlines()

setup(
    name='cloudlift',
    version=VERSION,
    packages=find_packages(),
    install_requires=requirements,
    zip_safe=True,
    entry_points='''
        [console_scripts]
        cloudlift=cloudlift:cli
    ''',
)
