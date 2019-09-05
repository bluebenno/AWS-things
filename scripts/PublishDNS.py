#!/usr/local/bin/python3

# PublishDNS.py

# Update/Create a DNS Cname 'to' a Stacks ELB
#   Often used to do a blue/green deployment via DNS

# examples
# ./PublishDNS.py --AWSRegion ap-southeast-2 --dnsname bentest.benno.ninja.com.au --stackname ben-test-v1

import argparse
import boto3
import subprocess
import sys
import time

# Allow this script to update the following
allowed_dns_zones = "benno.ninja,int.benno.ninja"

# How to wait(secs) for the dnscnametarget DNS to become available(in local DNS)
how_long_to_wait_for_dns = 300

# globals
aws_region      = None
boto_cfn        = None
boto_elb        = None
boto_r53        = None
dnscnametarget  = ""
dnsname         = ""
dnssuffix       = ""
live_dns_record = None
print_elb_dns   = True
show_debug      = False
stackname       = ""

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
    if show_debug:
        print(GREEN + 'debug::' + str(message) + ENDC)


def parsecommandline():
    global parser
    global args
    global aws_region
    global stackname
    global dnsname
    global show_debug
    global print_elb_dns

    parser = argparse.ArgumentParser(description = 'Utilitiy to add/update an AWS Route53 CNAMEs to a Stacks ELB')
    parser.add_argument('--AWSRegion', default = 'ap-southeast-2', help = "AWS Region")
    parser.add_argument('--Debug', default = None, required = False, help = "Set this to true for debug")
    parser.add_argument('--stackname', default = None, required = True, help = "The name of the stack  = > it MUST have an ELB")
    parser.add_argument('--dnsname', default = None, required = False, help = "The *FQDN* of the DNS name you want to set. i.e. foo.int.benno.ninjam.au")
    parser.add_argument('--get_elb_fqdn', action = 'store_const', const = True, default = False, required = False, help = "Dont change anything. Just get the DNSName of the ELB and exit")

    args = parser.parse_args()

    aws_region    = args.AWSRegion
    stackname     = args.stackname
    dnsname       = args.dnsname
    show_debug    = args.Debug
    print_elb_dns = args.get_elb_fqdn

def run_os_command(to_run):
    timeout = 3
    try:
        p = subprocess.Popen(to_run,
                            shell = True,
                            stdout = subprocess.PIPE,
                            stderr = subprocess.PIPE)

        ph_ret = p.wait()
        ph_ret = p.returncode
        ph_outb, ph_err = p.communicate()
        ph_out = str(ph_outb.decode("utf-8"))

        if p.returncode != 0:
            warning(to_run + " returned an error: " + str(ph_ret) + " " + str(ph_err) + " " + ph_out )
            return(-1)
        else:
            debug(str(to_run) + " returned 0" )
            debug(ph_out)
            return(ph_out)

    except:
        bail(str(to_run) + " : failed to run, triggering an exception: ")
        return(-1)

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
def get_r53_zoneid(domain):
    global boto_r53

    if domain[-1] !=  '.':
        domain +=  '.'

    for i in boto_r53.list_hosted_zones()['HostedZones']:
        if i['Name'] ==  domain:
            return i['Id'].replace('/hostedzone/', '')

    return -1


# kudos to https://chromium.googlesource.com/external/boto/+/cd1aa815051534a5371817e94dba4c03bb5488f1/bin/route53
# construct and send back a DNSCNameRecord Object
def get_r53_cname_rec(dns_rec):
    global boto_r53

    name = dns_rec.name + '.'
    res = boto_r53.list_resource_record_sets(HostedZoneId=dns_rec.zoneid, StartRecordType="CNAME", StartRecordName = name)['ResourceRecordSets']
    for record in res:
        print(record)
        if record["Name"] == name:
            dns_rec.dnscnametarget = record['ResourceRecords'][-1]['Value']
            dns_rec.ttl = record["TTL"]
            dns_rec.orignalttl = record["TTL"]
            return 0

    return(-1)


def get_stack_status(stack_name):
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


def set_r53_ttl(dns_rec, updated_ttl):
    global dnssuffix

    info(dns_rec.name +
        ' DNS TTL is ' +
        dns_rec.ttl +
        'secs, changing to ' +
        str(updated_ttl) + 'secs')

    ret = boto_r53.get_zone(dnssuffix).update_cname(dns_rec.name + "." + dnssuffix +".", dns_rec.dnscnametarget, ttl = int(updated_ttl), identifier = None, comment = 'was:'+str(dns_rec.orignalttl) + 'setdown for blue/green deployment')
    if 'Status:PENDING' in str(ret):
        return 0
    else:
        return 1

def set_r53_cname(dns_rec, updated_cname):
    global dnssuffix
    record = dns_rec.name + "."
    dnscnametarget = updated_cname + '.'
    info('updating DNS CNAME:' + record + ' to point to:' + dnscnametarget)

    CB= {
        'Comment': 'PublishDNS.py',
        'Changes': [{
            'Action': 'UPSERT',
            'ResourceRecordSet': {
                'Name': record,
                'Type': 'CNAME',
                'TTL': 60,
                'ResourceRecords': [{'Value': updated_cname}]
            }
        }]
    }

    ret = boto_r53.change_resource_record_sets(HostedZoneId=dns_rec.zoneid, ChangeBatch=CB)
    if ret['ResponseMetadata']['HTTPStatusCode'] != 200 or ret['ChangeInfo']['Status'] != "PENDING":
        bail("AWS rejected update:" + str(ret))

    info("AWS requestid:" + str(ret['ResponseMetadata']['RequestId']))

    # update object
    dns_rec.dnscnametarget = dnscnametarget
    return 0


def add_r53_cname(dns_rec, updated_cname):
    global dnssuffix
    record = dns_rec.name + "."
    dnscnametarget = updated_cname + '.'

    info('Adding DNS CNAME:' + record + ' pointing to :' + dnscnametarget)

    # Todo: Not hardcode the DNS(min) value
    ret = boto_r53.get_zone(dnssuffix).add_cname(record, dnscnametarget, ttl = 60, identifier = None, comment = 'PublishDNS.py')
    if 'Status:PENDING' in str(ret):
        dns_rec.dnscnametarget = dnscnametarget
        time.sleep(5)
        return 0
    else:
        return 1


def PollForHostnameResolve(host, max_wait):
    progress('polling for resolution on :' + host)
    if sys.platform == "darwin":
        command = "/usr/bin/dscacheutil -q host -a name"
    else:
        command = "getent hosts"

    for i in range(1,int(max_wait)):
        ret = run_os_command(command + " " + host + " | grep -i " + host )
        if ret !=  -1:
            info('confirm that ' + host + ' is resolvable')
            return 0

        info('polling for resolution on :' + host)
        time.sleep(10)

    info('Timeout waiting for resolution on hostname:' + host + ' -> failing')
    return -1


def poll_for_cname_update(host, match, max_wait ):
    progress('polling for CNAME resolution :' + host)

    for i in range(1,int(max_wait) ):
        ret = run_os_command('dig +short -t CNAME ' + host)
        if ret == -1:
            bail("internal error failure with dig command in poll_for_cname_update")

        if ret.rstrip().lower() == match.lower() + '.':
            info('CNAME match:' + host + '  = > ' + match)
            return 0

        time.sleep(10)
        info('polling for CNAME resolution :' + host)

    info('Timeout waiting for resolution on CNAME:' + host)
    return -1


def parse_dns_suffix(ldnsname):
    global allowed_dns_zones

    for anallowed in reversed(sorted(allowed_dns_zones.split(','), key = len) ):
        if anallowed in ldnsname:
            debug('matched(allowed) DNS zone: ' + str(anallowed))
            return anallowed
    return -1


def get_first_elb_from_stack(stack_name):
    global boto_cfn
    sr = boto_cfn.list_stack_resources(StackName=stack_name)

    for i in sr['StackResourceSummaries']:
        if i['LogicalResourceId'] == "LoadBalancer":
            return i['PhysicalResourceId']

    return -1


def get_elb_fqdn(lelbname):
    global boto_elb
    return boto_elb.describe_load_balancers(LoadBalancerNames=[lelbname])['LoadBalancerDescriptions'][-1]['DNSName']


def main():
    dnscnametarget = -1
    parsecommandline()
    botoconnects()

    ret = get_stack_status(stackname)
    if ret ==  -1:
        bail('stack not found, cannot find stack with name:' + str(stackname) )
    if 'COMPLETE' not in ret :
        bail('stack not in COMPLETE state, stack(' + str(stackname) + ') in state(' + str(ret) + ')' )

    elb = get_first_elb_from_stack(stackname)
    if elb ==  -1:
        bail('ELB not found, cannot find ELB for stack(' + stackname)
    else:
        info('Stack(' + stackname + '), found ELB:' + elb)
        dnscnametarget = get_elb_fqdn(elb)

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

    ret = parse_dns_suffix(dnsname)
    if ret ==  -1:
        bail('invalid DNSSuffix. Parsing(' + str(dnsname) + ') could not find in ALLOWED DNS Suffixs(' + str(allowed_dns_zones) + ')')
    else:
        dnssuffix = ret

    zone_id = get_r53_zoneid(dnssuffix + '.')
    info('Using AWS zoneid:'+zone_id + ' for ' + dnssuffix)

    live_dns_record = DNSCNameRecord(dnsname)
    live_dns_record.zoneid = zone_id

    # does it exist?  If it does we record the details
    ret = get_r53_cname_rec(live_dns_record)

    if ret ==  0:
        info(str(dnsname) + ' already exists, dig follows...')
        info(str(run_os_command('dig ' + dnsname) ))
        info('TTL = ' +str(live_dns_record.ttl) + ' seconds')
        info('-----------------------------------------------------------------------------')
        ret =  set_r53_cname(live_dns_record, dnscnametarget)
    else:
        ret =  add_r53_cname(live_dns_record, dnscnametarget)

    if ret !=  int(0):
        warning('warning: Route53 DNS CNAME add/update returned an error and may have failed! Will continue to polling for result')

    if live_dns_record.ttl ==  None:
        live_dns_record.ttl = 60

    ret =  poll_for_cname_update(live_dns_record.name + '.' , dnscnametarget ,(live_dns_record.ttl*2))
    if ret ==  -1:
        bail('DNS CNAME update fail, the DNS CNAME update has not propergated')

    info(live_dns_record.name + ' -> ELB(stack = ' + stackname + ')' )


if __name__ == "__main__":
    main()