#!/usr/local/bin/python3

# PublishDNS.py

# Update/Create a DNS Cname 'to' a Stacks ELB
#   Often used to do a blue/green deployment via DNS

# examples
# ./PublishDNS.py --AWSRegion ap-southeast-2 --dnsname bentest.benno.ninja.com.au --stackname ben-test-v1

from datetime import datetime
import argparse
import boto3
import datetime
import os
import re
import subprocess
import sys
import time
import time

# Allow
allowed_dns_zones = "benno.ninja.com.au,int.benno.ninja.com.au"

# How to wait(secs) for the dnscnametarget DNS to become available(in local DNS)
how_long_to_wait_for_dns = 300

# globals
aws_region = None
boto_cfn   = None
boto_elb   = None
boto_r53   = None
debug      = False
dnscnametarget  = ""
dnssuffix       = ""
live_dns_record = None
print_elb_dns   = True
stackname  = ""

# Pretty Colours
PINK = '\033[95m'
BLUE = '\033[94m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
ENDC = '\033[0m'


class DNSCNameRecord:
    'A DNS Record'
    def __init__(self, name):
        self.name = name
        self.zoneid = None
        self.dnscnametarget = None
        self.ttl = None
        self.orignalttl = None


def bail(message):
    print(RED + message.replace('<message text>', message) + ENDC)
    sys.exit(1)


def warning(message):
    print(YELLOW + message.replace('<message text>', message) + ENDC)


def info(message):
    print(message.replace('<message text>', message))


def progress(message):
    print(GREEN + message.replace('<message text>', message) + ENDC)


def debug(message):
    if debug:
        print(GREEN + 'debug::' + str(message) + ENDC)


def parsecommandline():
    global parser
    global args
    global aws_region
    global stackname
    global dnsname
    global debug
    global print_elb_dns

    parser = argparse.ArgumentParser(description = 'Utilitiy to add/update an AWS Route53 CNAMEs to a Stacks ELB')
    parser.add_argument('--AWSRegion', default = 'ap-southeast-2', help = "AWS Region")
    parser.add_argument('--Debug', default = None, required = False, help = "Set this to true for debug")
    parser.add_argument('--stackname', default = None, required = True, help = "The name of the stack  = > it MUST have an ELB")
    parser.add_argument('--dnsname', default = None, required = False, help = "The *FQDN* of the DNS name you want to set. i.e. foo.int.benno.ninjam.au")
    parser.add_argument('--getelbdnsname', action = 'store_const', const = True, default = False, required = False, help = "Dont change anything. Just get the DNSName of the ELB and exit")

    args = parser.parse_args()

    aws_region    = args.AWSRegion
    stackname     = args.stackname
    dnsname       = args.dnsname
    debug         = args.Debug
    print_elb_dns = args.getelbdnsname

def RunCommandFore(ltorun):
    try:
        timeout = 3
        p = subprocess.Popen(ltorun,
                            shell = True,
                            stdout = subprocess.PIPE,
                            stderr = subprocess.PIPE)

        ph_ret = p.wait()
        ph_ret = p.returncode
        ph_out, ph_err = p.communicate()

        if p.returncode != 0:
            debug(ltorun + " : returned an error: " + str(ph_ret) + " " + str(ph_err) + " " + ph_out )
            return(-1)
        else:
            debug(str(ltorun) + " : returned 0" )
            debug(str(ph_out))
            return(str(ph_out))

    except:
        bail(str(ltorun) + " : failed to run, triggering an exception: ")

def botoconnects():
    global aws_region
    global boto_cfn
    global boto_elb
    global boto_r53

    boto_cfn = boto3.client('cloudformation',region_name=aws_region)
    boto_elb = boto3.client('elb',region_name=aws_region)
    boto_r53 = boto3.client('route53',region_name=aws_region)

    for con in boto_cfn, boto_elb, boto_r53:
        if con is None:
            bail("A boto connect failed","Boto connect failed connecting to AWS Region:" + str(aws_region) + " failed")

    return True

# Give me a domain name, I'll respond with the AWS HostedZoneID
def GetR53ZoneID(ldomain):
    global boto_r53
    if ldomain[-1] !=  '.':
        ldomain +=  '.'

    for i in boto_r53.get_all_hosted_zones(start_marker = None, zone_list = None)['ListHostedZonesResponse']['HostedZones']:
        if i['Name'] ==  ldomain:
            return i['Id'].replace('/hostedzone/', '')


# kudos to https://chromium.googlesource.com/external/boto/+/cd1aa815051534a5371817e94dba4c03bb5488f1/bin/route53
# construct and send back a DNSCNameRecord Object
def GetR53CRecord(ldnsrec):
    global boto_r53
    global zone_id

    lname = ldnsrec.name + '.' #+ dnssuffix + '.'

    res = boto_r53.get_all_rrsets(zone_id, type = "CNAME", name = lname)
    for record in res:
        #print '%-40s %-5s %-20s %s' %(record.name, record.type, record.ttl, record.to_print())
        if record.name == lname:
            ldnsrec.zoneid = zone_id
            ldnsrec.dnscnametarget = record.to_print()
            ldnsrec.ttl = record.ttl
            ldnsrec.orignalttl = record.ttl
            return 0
    # not found return -1
    return(-1)


def StackStatus(stack_name):
    global aws_region
    global boto_cfn

    try:
        stk = boto_cfn.describe_stacks(StackName=stack_name)
        if stk['Stacks'][-1]['StackName'] == stack_name:
            return stk['Stacks'][-1]['StackStatus']

    except boto_cfn.exceptions.ClientError as e:
        if e.response['Error']['Message'] == "Stack with id " + stack_name + " does not exist":
            bail("unable to find stack:" + stack_name + " ,in region:" + aws_region)

        bail("Internal Error in def StackStatus. Failed to parse the error output from cloudformation via boto")


def SetDNSCnameTTL(ldnsobject, lnewttl):
    global dnssuffix
    info(ldnsobject.name +
        ' DNS TTL is ' +
        ldnsobject.ttl +
        'secs, changing to ' +
        str(lnewttl) + 'secs')
    ret = boto_r53.get_zone(dnssuffix).update_cname(ldnsobject.name + "." + dnssuffix +".", ldnsobject.dnscnametarget, ttl = int(lnewttl), identifier = None, comment = 'was:'+str(ldnsobject.orignalttl) + 'setdown for blue/green deployment')
    if 'Status:PENDING' in str(ret):
        return 0
    else:
        return 1

def SetDNSCNAME(ldnsobject, lnewcname):
    global dnssuffix
    record = ldnsobject.name + "."# + dnssuffix + "."
    dnscnametarget = lnewcname + '.'
    info('updating DNS CNAME:' + record + ' to point to:' + dnscnametarget)
    # we keep the DNS at min value
    ret = boto_r53.get_zone(dnssuffix).update_cname(record, dnscnametarget, ttl = 60, identifier = None, comment = 'PublishDNS.py')
    if 'Status:PENDING' in str(ret):
        # update object & safety sleep
        ldnsobject.dnscnametarget = dnscnametarget
        #time.sleep(30)
        time.sleep(1)
        return 0
    else:
        return 1

def AddDNSCNAME(ldnsobject, lnewcname):
    global dnssuffix
    record = ldnsobject.name + "."# + dnssuffix + "."
    dnscnametarget = lnewcname + '.'

    info('Adding DNS CNAME:' + record + ' pointing to :' + dnscnametarget)

    # Todo: Not hardcode the DNS(min) value
    ret = boto_r53.get_zone(dnssuffix).add_cname(record, dnscnametarget, ttl = 60, identifier = None, comment = 'PublishDNS.py')
    if 'Status:PENDING' in str(ret):
        ldnsobject.dnscnametarget = dnscnametarget
        time.sleep(5)
        return 0
    else:
        return 1

def PollForHostnameResolve(lhost, lalarm):
    progress('polling for resolution on :' + lhost)
    for i in range(1,int(lalarm)):
        ret = RunCommandFore('getent hosts ' + lhost)
        if ret !=  -1:
            info('confirm that ' + lhost + ' is resolvable')
            return 0

        info('polling for resolution on :' + lhost)
        time.sleep(10)

    info('Timeout waiting for resolution on hostname:' + lhost + ' -> failing')
    return -1

def PollForCNAMESwitch(lhost, lmatch, lalarm ):
    progress('polling for CNAME resolution :' + lhost)
    for i in range(1,int(lalarm) ):
        ret = RunCommandFore('getent hosts ' + lhost)
        if ret != -1:
            dnscnametarget = re.search('^(\d+).(\d+).(\d+).(\d+)\s+(\S+).*', ret, flags = 0)
            if dnscnametarget:
                if dnscnametarget.group(5).lower() ==  lmatch.lower():
                    info('CNAME match:' + lhost + '  = > ' + lmatch)
                    return 0

        info('polling for CNAME resolution :' + lhost)
        time.sleep(10)

    info('Timeout waiting for resolution on CNAME:' + lhost)
    return -1

def parseDNSSuffix(ldnsname):
    global allowed_dns_zones

    for anallowed in reversed(sorted(allowed_dns_zones.split(','), key = len) ):
        if anallowed in ldnsname:
            debug('matched(allowed) DNS zone: ' + str(anallowed))
            return anallowed
    return -1


def GetFirstELBFromStack(stack_name):
    global boto_cfn
    sr = boto_cfn.list_stack_resources(StackName=stack_name)

    for i in sr['StackResourceSummaries']:
        if i['LogicalResourceId'] == "LoadBalancer":
            return i['PhysicalResourceId']

    return -1


def GetELBDNSName(lelbname):
    global boto_elb
    return boto_elb.describe_load_balancers(LoadBalancerNames=[lelbname])['LoadBalancerDescriptions'][-1]['DNSName']


def main():
    dnscnametarget = -1
    parsecommandline()
    botoconnects()

    ret = StackStatus(stackname)
    if ret ==  -1:
        bail('stack not found, cannot find stack with name:' + str(stackname) )
    if 'COMPLETE' not in ret :
        bail('stack not in COMPLETE state, stack(' + str(stackname) + ') is not in a COMPLETE state(' + str(ret) + ')' )

    elb = GetFirstELBFromStack(stackname)
    if elb ==  -1:
        bail('ELB not found, cannot find ELB for stack(' + stackname)
    else:
        info('Stack(' + stackname + '), found ELB:' + elb)
        dnscnametarget = GetELBDNSName(elb)

    if dnscnametarget ==  -1:
        bail('internal error, the DNS dnscnametarget is invalid')
    if len(dnscnametarget) < 20:    # todo: don't hardcode this
        bail('internal error, the DNS dnscnametarget is not sane(too short - under 20chars)')

    # if this is a very new stack, the ELB name might not yet resolve, so poll...
    ret = PollForHostnameResolve(dnscnametarget, how_long_to_wait_for_dns)
    if ret ==  -1:
        bail('Timeout on resolution of the ELB DNS name. ' + str(dnscnametarget) + ' does not resolve')

    # just print elb dns name and exit...
    if print_elb_dns ==  True:
        print(dnscnametarget)
        sys.exit(0)

    ret = parseDNSSuffix(dnsname)
    if ret ==  -1:
        bail('invalid DNSSuffix', 'Parsing(' + str(dnsname) + ') couldnt find in an ALLOWED DNS Suffixs(' + str(allowed_dns_zones) + ')')
    else:
        dnssuffix = ret

    zone_id = GetR53ZoneID(dnssuffix + '.')
    info('Using AWS zoneid:'+zone_id + ' for ' + dnssuffix)

    # does the dnsname already exist? if yes record it, then switch it
    live_dns_record = DNSCNameRecord(dnsname)
    ret = GetR53CRecord(live_dns_record)
    if ret ==  0:
        info(str(dnsname) + ' already exists, dig follows...')
        info(str(RunCommandFore('dig ' + dnsname) ))
        info('TTL = ' +str(live_dns_record.ttl) + ' seconds')
        info('-----------------------------------------------------------------------------')
        ret =  SetDNSCNAME(live_dns_record, dnscnametarget)
    else:
        ret =  AddDNSCNAME(live_dns_record, dnscnametarget)

    if ret !=  int(0):
        warning('warning: Route53 DNS CNAME add/update returned an error and may have failed! Will continue to polling for result')

    if live_dns_record.ttl ==  None:
        live_dns_record.ttl = 60

    ret =  PollForCNAMESwitch(live_dns_record.name + '.' , dnscnametarget ,(live_dns_record.ttl*2))
    if ret ==  -1:
        bail('DNS CNAME update fail, the DNS CNAME update has not propergated')

    info(live_dns_record.name + ' -> ELB(stack = ' + stackname + ')' )

if __name__ == "__main__":
    main()