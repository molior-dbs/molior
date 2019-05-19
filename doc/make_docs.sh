#!/bin/bash

export IS_SPHINX=1
sphinx-apidoc --force --separate -o source/molior/ ../molior
make html
