#!/usr/local/bin/python3

# publish_dns.py

# Update/Create a DNS Cname 'to' a Stacks ELB
#   Often used to do a blue/green deployment via DNS

# examples

# Just print the DNS name of the ELB in stack ben-test-v1
# ./PublishDNS.py --AWSRegion ap-southeast-2 \
#                 --DNSTarget foobar.com.au \
#                 --stackname ben-test-v1 \
#                 --getELBDNS

# Add or update 'example.ninja.com.au' to point to the ELB in stack ben-test-v1
# ./PublishDNS.py --AWSRegion ap-southeast-2 \
#                 --DNSTarget foobar.com.au \
#                 --stack_name ben-test-v1

import argparse
import boto3
import subprocess
import sys
import time

# Secs for _cname_target DNS to become available(in local DNS)
MAX_WAIT = 300

# Pretty Colours
PINK = '\033[95m'
BLUE = '\033[94m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
ENDC = '\033[0m'

# globals
_AWS_region = None
_boto_cfn = None
_boto_ELB = None
_boto_r53 = None
_DNS_target = ""
_DNS_suffix = ""
_live_dns_record = None
_print_elb_dns = True
_show_debug = False
_stack_name = ""


class DNSCNameRecord:
    'A DNS Record'
    def __init__(self, name):
        self.name = name
        self.zoneid = None
        self.cname = None
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
    if _show_debug:
        print(GREEN + 'debug::' + str(message) + ENDC)


def parsecommandline():
    global _AWS_region
    global _stack_name
    global _DNS_target
    global _show_debug
    global _print_elb_dns

    parser = argparse.ArgumentParser(description='Utilitiy to add/update an '
                                     'AWS Route53 CNAME to point to a'
                                     'Cloudformation Stacks ELB')

    parser.add_argument('--AWSRegion',
                        default=None,
                        required=True,
                        help="AWS Region")
    parser.add_argument('--debug',
                        action='store_const',
                        const=True,
                        default=None,
                        required=False,
                        help="true for debug")
    parser.add_argument('--stackname',
                        default=None,
                        required=True,
                        help='Name of the CFN stack, MUST have one ELB')
    parser.add_argument('--DNSTarget',
                        default=None,
                        required=False,
                        help='FQDN DNS taret name you want to set/update')
    parser.add_argument('--GetELBDNS',
                        action='store_const',
                        const=True,
                        default=False,
                        required=False,
                        help='No changes. Just output DNS name of the ELB')

    args = parser.parse_args()
    _AWS_region = args.AWSRegion
    _stack_name = args.stackname
    _DNS_target = args.DNSTarget
    _show_debug = args.debug
    _print_elb_dns = args.GetELBDNS


def run_os_command(to_run):
    try:
        p = subprocess.Popen(to_run,
                             shell=True,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)

        ph_ret = p.wait()
        ph_ret = p.returncode
        ph_outb, ph_err = p.communicate()
        ph_out = str(ph_outb.decode("utf-8"))

        if p.returncode != 0:
            warning(to_run +
                    " returned an error: " +
                    str(ph_ret) + " " +
                    str(ph_err) + " " +
                    ph_out)
            return -1
        else:
            debug(str(to_run) + " returned 0")
            debug(ph_out)
            return ph_out

    except:
        bail(str(to_run) + " failed: ")
        return -1


def do_boto_setup():
    global _AWS_region
    global _boto_cfn
    global _boto_ELB
    global _boto_r53

    _boto_cfn = boto3.client('cloudformation', region_name=_AWS_region)
    _boto_ELB = boto3.client('elb', region_name=_AWS_region)
    _boto_r53 = boto3.client('route53', region_name=_AWS_region)

    for con in _boto_cfn, _boto_ELB, _boto_r53:
        if con is None:
            bail("boto failed in AWS Region:" + str(_AWS_region))

    return True


# Give me a domain name, I'll respond with the AWS HostedZoneID
def get_r53_zoneid(domain):
    global _boto_r53

    if domain[-1] != '.':
        domain += '.'

    for i in _boto_r53.list_hosted_zones()['HostedZones']:
        if i['Name'] == domain:
            return i['Id'].replace('/hostedzone/', '')

    return -1


# construct and send back a DNSCNameRecord Object
def get_r53_cname_rec(dns_rec):
    global _boto_r53

    name = dns_rec.name + '.'
    res = _boto_r53.list_resource_record_sets(
        HostedZoneId=dns_rec.zoneid,
        StartRecordType="CNAME",
        StartRecordName=name)['ResourceRecordSets']

    for record in res:
        if record["Name"] == name:
            dns_rec._cname_target = record['ResourceRecords'][-1]['Value']
            dns_rec.ttl = record["TTL"]
            dns_rec.orignalttl = record["TTL"]
            return 0

    return(-1)


def get_stack_status(stack_name):
    global _AWS_region
    global _boto_cfn

    try:
        stk = _boto_cfn.describe_stacks(StackName=stack_name)
        if stk['Stacks'][-1]['StackName'] == stack_name:
            return stk['Stacks'][-1]['StackStatus']

    except _boto_cfn.exceptions.ClientError as e:
        if e.response['Error']['Message'] == "Stack with id " + _stack_name + " does not exist":
            bail("unable to find stack:"
                 + stack_name
                 + " ,in region:"
                 + _AWS_region)

    bail("Internal Error in def StackStatus."
         "Failed to parse the error output from cloudformation via boto")


# TODO a) does this work, b) is it used, c) should be used?
def set_r53_ttl(dns_rec, updated_ttl):
    global _DNS_suffix

    info(dns_rec.name +
         ' DNS TTL is ' +
         dns_rec.ttl +
         'secs, changing to ' +
         str(updated_ttl) + 'secs')

    ret = _boto_r53.get_zone(_DNS_suffix).update_cname(
        dns_rec.name
        + "." + _DNS_suffix
        + ".", dns_rec._cname_target,
        ttl=int(updated_ttl),
        identifier=None,
        comment='was:'+str(dns_rec.orignalttl) + 'setdown')
    if 'Status:PENDING' in str(ret):
        return 0
    else:
        return 1


def update_r53(dns_rec, updated_cname):
    global _boto_r53
    global _DNS_suffix
    record = dns_rec.name + "."
    _cname_target = updated_cname + '.'
    info('updating DNS CNAME:' + record + ' to point to:' + _cname_target)

    CB = {
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

    ret = _boto_r53.change_resource_record_sets(HostedZoneId=dns_rec.zoneid,
                                                ChangeBatch=CB)
    if ret['ResponseMetadata']['HTTPStatusCode'] != 200 or ret['ChangeInfo']['Status'] != "PENDING":
        bail("AWS rejected update:" + str(ret))

    info("AWS requestid:" + str(ret['ResponseMetadata']['RequestId']))

    # update object
    dns_rec._cname_target = _cname_target
    return 0


# TODO: The loop can be too short (TTL things)
def PollForHostnameResolve(host, max_wait):
    progress('polling for resolution on:' + host)
    if sys.platform == "darwin":
        command = "/usr/bin/dscacheutil -q host -a name"
    else:
        command = "getent hosts"

    for i in range(1, int(max_wait)):
        ret = run_os_command(command + " " + host + " | grep -i " + host)
        if ret != -1:
            info('confirm: ' + host + ' now resolvable')
            return 0

        progress('polling for resolution on:' + host + " #" + str(i))
        time.sleep(10)

    warning('Timeout waiting for resolution on hostname:' + host)
    return -1


def poll_for_cname_update(host, match, max_wait):
    progress('polling for CNAME resolution :' + host)

    for i in range(1, int(max_wait)):
        ret = run_os_command('dig +short -t CNAME ' + host)
        if ret == -1:
            bail("internal error failure with dig command in"
                 " poll_for_cname_update")

        if ret.rstrip().lower() == match.lower() + '.':
            debug('CNAME match:' + host + '  => ' + match)
            return 0

        time.sleep(10)
        info('polling for CNAME resolution:' + host + " #" + str(i))

    info('Timeout waiting for resolution on CNAME:' + host)
    return -1


# parse and validate the dns suffix (aka hosted_zone_name)
def parse_dns_suffix(_DNS_target):
    global _boto_r53

    hosted_zone_name = ".".join(_DNS_target.split(".")[1:])

    if get_r53_zoneid(hosted_zone_name) == -1:
        warning("Not a hosted zone for this AWS account")
        return -1

    return hosted_zone_name


def get_first_elb_from_stack(stack_name):
    global _boto_cfn
    sr = _boto_cfn.list_stack_resources(StackName=stack_name)

    for i in sr['StackResourceSummaries']:
        if i['LogicalResourceId'] == "LoadBalancer":
            return i['PhysicalResourceId']

    return -1


def GetELBDNS(elb):
    global _boto_ELB
    # TODO what if there isn't an ELB (or there is two)

    ret = _boto_ELB.describe_load_balancers(
        LoadBalancerNames=[elb])['LoadBalancerDescriptions'][-1]['DNSName']
    return ret


def main():
    parsecommandline()
    do_boto_setup()

    ret = get_stack_status(_stack_name)
    if ret == -1:
        bail('stack not found, cant find stack with name:' + str(_stack_name))
    if 'COMPLETE' not in ret:
        bail('stack not in COMPLETE state. Stack:'
             + str(_stack_name)
             + ' :' + str(ret))

    elb = get_first_elb_from_stack(_stack_name)
    if elb == -1:
        bail('ELB not found, cannot find ELB for stack(' + _stack_name)
    else:
        info('Stack(' + _stack_name + '), found ELB:' + elb)
        _cname_target = GetELBDNS(elb)

    if _cname_target == -1:
        bail('internal error, the DNS _cname_target is invalid')

    # For new stacks; ELB name won't be resolvable yet, so poll...
    ret = PollForHostnameResolve(_cname_target, MAX_WAIT)
    if ret == -1:
        bail('Timeout on resolution of the ELB DNS name. '
             + str(_cname_target)
             + ' does not resolve')

    # just print elb dns name and exit...
    if _print_elb_dns is True:
        print(_cname_target)
        sys.exit(0)

    ret = parse_dns_suffix(_DNS_target)
    if ret == -1:
        bail('invalid _DNS_suffix:' + str(_DNS_target))
    else:
        _DNS_suffix = ret

    zone_id = get_r53_zoneid(_DNS_suffix + '.')
    info('Using AWS zoneid:'+zone_id + ' for ' + _DNS_suffix)

    _live_dns_record = DNSCNameRecord(_DNS_target)
    _live_dns_record.zoneid = zone_id

    # does it exist?  If it does we record the details
    ret = get_r53_cname_rec(_live_dns_record)

    if ret == 0:
        info(str(_DNS_target) + ' already exists, dig follows...')
        info('--------------------------------------------------------------')
        info(str(run_os_command('dig ' + _DNS_target)))
        info('--------------------------------------------------------------')
        info('TTL = ' + str(_live_dns_record.ttl) + ' seconds')

    ret = update_r53(_live_dns_record, _cname_target)
    if ret != int(0):
        warning('warning: Route53 DNS CNAME add/update returned an error '
                'and may have failed! Will continue to polling for result')

    if _live_dns_record.ttl is None:
        _live_dns_record.ttl = 60
    ret = poll_for_cname_update(_live_dns_record.name
                                + '.', _cname_target,
                                (_live_dns_record.ttl*2))
    if ret == -1:
        bail('DNS CNAME update fail, the DNS CNAME update has not propergated')

    info(_live_dns_record.name + ' -> ELB(stack = ' + _stack_name + ')')


if __name__ == "__main__":
    main()
