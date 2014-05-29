#! /bin/sh

set -e

set -e

git fetch
ansible-playbook -i hosts gateway.yml
