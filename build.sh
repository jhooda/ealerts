#!/bin/bash -ex
# This command build a lamda function package to run on AWS
which python || { echo "Python is required to use this package. Exit!" && exit 1 ; }
MYDIR=$(cd $(dirname ${BASH_SOURCE[0]:-$0}); pwd)
pushd ${MYDIR}
[[ -d requests ]] || pip install -t ${MYDIR} requests
[[ -d boto ]] || pip install -t ${MYDIR} boto
zip -FS -r9 ealerts.zip ealerts.py requests boto --exclude \*.pyc
MD5SUM=md5
which md5 || MD5SUM=md5sum
${MD5SUM} ealerts.zip
popd
