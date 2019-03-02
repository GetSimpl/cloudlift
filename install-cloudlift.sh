#!/bin/bash

VENV_DIRNAME="venv"
QUIET="-q"

if [[ $1 == '-v' ]]; then
    QUIET=""
fi

if ! [ -d "$VENV_DIRNAME" ]; then
   pip install virtualenv $QUIET
   virtualenv -p python3 $VENV_DIRNAME $QUIET
fi
source `pwd`/$VENV_DIRNAME/bin/activate
echo "Installing requirements..."
pip install -r requirements.txt $QUIET
pip uninstall -y cloudlift 2>/dev/null 1>/dev/null
rm -rf cloudlift.egg-info/ build/ dist/ && python setup.py $QUIET install
rm /usr/local/bin/cloudlift
ln -s `pwd`/$VENV_DIRNAME/bin/cloudlift /usr/local/bin/cloudlift

if ! command -v "cloudlift" > /dev/null; then
echo '''
  Failed to install cloudlift. Run installation with -v for details
'''
else
echo '''
        _                    _  _  _   __  _
   ___ | |  ___   _   _   __| || |(_) / _|| |_
  / __|| | / _ \ | | | | / _` || || || |_ | __|
 | (__ | || (_) || |_| || (_| || || ||  _|| |_
  \___||_| \___/  \__,_| \__,_||_||_||_|   \__|

 run cloudlift --help to know more.
'''
fi
