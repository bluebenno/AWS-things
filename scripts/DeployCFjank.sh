#!/bin/bash

# simple script to launch something

export AWS_DEFAULT_REGION="ap-southeast-2"

STACKNAME=$1
TEMPLATEFN=$2
FQTFN="`pwd`/${TEMPLATEFN}"

aws cloudformation validate-template --template-body file:///${FQTFN}
if [ $? -ne 0 ]
then
    echo "$TEMPLATEFN failed validation"
    exit 1
fi


aws cloudformation create-stack --stack-name $STACKNAME --template-body file:////${FQTFN} --parameters \
ParameterKey="InstanceType",ParameterValue="t2.nano" \
ParameterKey="NetworkName",ParameterValue="sandpit-internetfacing" \
ParameterKey="Env",ParameterValue="sandpit" \
ParameterKey="SSHKey",ParameterValue="Nov2017" \

sleep 10
aws cloudformation list-stacks --stack-status-filter CREATE_IN_PROGRESS
