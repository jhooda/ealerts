#!/bin/bash -ex
# Clean any alerted flag to repeat test
which python || { echo "Python is required to use this package. Exit!" && exit 1 ; }
MYDIR=$(cd $(dirname ${BASH_SOURCE[0]:-$0}); pwd)
MYNAME=$(basename $0)
pushd ${MYDIR}
JSNFLN=${MYNAME//.sh/}.json
[[ -f ${JSNFLN} ]] || { echo "Please generate a file ${JSNFLN} as per template ${JSNFLN}.template"; exit 1; }
LCKFLN=$(grep alert_type ${JSNFLN} | cut -d'"' -f4)
LCKFLN=${LCKFLN,,}
python ../ealerts.py ${JSNFLN}
popd
