#!/bin/bash

cd $APP_HOME

bundle exec rackup --host 0.0.0.0 -p $PORT
