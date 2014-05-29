#! /bin/sh

set -e

tags=""
test -n "$1" && tags="--tags=$1"

git pull
ansible-playbook -i hosts gateway.yml $tags
