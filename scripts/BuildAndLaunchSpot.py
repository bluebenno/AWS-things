#!/usr/bin/python

# I used this to launch spot nodes - back in the day, it relies on my puppet3 server (now dead, burried and cremated)

import sys
import os
import subprocess
import re
import json

# puppet cert files (YMMV)
PUPPETCERTPK="/var/lib/puppet/ssl/private_keys/<NODENAME>.pem"
PUPPETCERTME="/var/lib/puppet/ssl/certs/<NODENAME>.pem"
PUPPETCERTPM="/var/lib/puppet/ssl/certs/ca.pem"

# puppet site.pp file - I expect to find the nodes in here
PUPPETSITEPP="/etc/puppet/manifests/site.pp"

class ANode:
    'A node - it will be an EC2 instance'
    def __init__(self, name):
        self.name = name
        self.privatekey = ""
        self.cert = ""
        self.privatekeyfn = ""
        self.certfn = ""
        self.jcode = ""
        self.jtextpk = ""
        self.jtextc = ""

def error( ltxt ):
    print "error : " + str( ltxt )
    sys.exit(1)

def usage():
    print "AWSandELBandDemoWebServer.py uploads and then creates a demowebserver (ELB and two nodes) stack in AWS - bootstrapping the two nodes from puppet"
    print "AWSandELBandDemoWebServer.py <stack name> <cloudformation json template> <demowebserver01> <demowebserver02>"
    sys.exit(1)

def RunCommandFore( ltorun ):
    try:
        timeout = 30

        print "executing: " + ltorun
        # execute
        p = subprocess.Popen( ltorun, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        ph_ret = p.wait()
        ph_ret = p.returncode
        ph_out, ph_err = p.communicate()

        if p.returncode != 0:
            error( str(ltorun) + " : returned an error: " + str( ph_ret ) + " " + str( ph_err ) + " " + ph_out )
            return(-1)
        else:
            #print str(ltorun) + " : returned 0" 
            #print str(ph_out)
            return(0)

    # some exception
    except OSError as e:
        error( str(ltorun) + " : failed to run and triggered an exception " + str(ltorun) + ": error({0}): {1}".format(e.errno, e.strerror))

def DoPuppetCerts( llistofnodes ):
    if os.path.isfile( PUPPETCERTPM ) == False:
        error("I cannot find the PuppetMaster ca.pem file. expecting==" + PUPPETCERTPM )

    for anode in llistofnodes.values():
        anode.privatekeyfn = PUPPETCERTPK.replace('<NODENAME>',anode.name )
        anode.certfn = PUPPETCERTME.replace('<NODENAME>',anode.name )

        if os.path.isfile( anode.privatekeyfn ) and os.path.isfile( anode.certfn ):
            print "puppet certs already exist for node:" + anode.name + " => " + anode.privatekeyfn, anode.certfn

        else:
            print "No puppet cert(s) found for node:" + anode.name
            RunCommandFore("/usr/bin/puppet ca generate " + anode.name )

            if os.path.isfile( anode.privatekeyfn ) and os.path.isfile( anode.certfn ):
                print "puppet certs now exist for node:" + anode.name + " => " + anode.privatekeyfn, anode.certfn
            else:
                error("failed to generate puppet certs")
    return(0)

# is it (pre) setup in puppet - I like each node clearly in site.pp (YMMV) & their has to be a better way ?!
def CheckSitepp( llistofnodes ):

    if os.path.isfile( PUPPETSITEPP ) == False:
        error("cannot open puppet site.pp to check the nodes are configured in it. expected: " + PUPPETSITEPP )

    fo = open( PUPPETSITEPP, 'r' )

    for anode in llistofnodes.values(): 
        found=0
        for aline in fo:
            # skip comments
            if re.match('^\s*#', aline ):
                continue
            if re.match('^\s*node.+' + anode.name + '.+\s*{' , aline ):
                found=1

        if found == 0:
            error("could not find node (" + anode.name + ") in site.pp file (" + PUPPETSITEPP + ") - please update the manfifest and rerun")
        # rewind 
        fo.seek(0)

    fo.close 
    return(0)


def WriteJSONParmFile( lofile, llistofnodes ):
    data = []

    # add CA ( the CA doesn't seem required )
    #with open ( PUPPETCERTPM, "r") as myfile:
    #    pmc=myfile.read().replace('\n', '')
    #data.append(   { "ParameterKey":"PuppetCertPuppetMasterCert", "ParameterValue": pmc } )

    for anode in llistofnodes.values():
        # slurp - privatekey
        with open ( anode.privatekeyfn, "r") as myfile:
            anode.privatekey=myfile.read().replace('\n', '<%%%>')

        # slurp - mycert
        with open ( anode.certfn, "r") as myfile:
            anode.cert=myfile.read().replace('\n', '<%%%>')

        # 1. pk (hack - todo readin the json...)
        if anode.name.count('1') > 0: 
            data.append(   { "ParameterKey":"Server1Name", "ParameterValue": anode.name } )
            data.append(   { "ParameterKey":"Server1PuppetCertMyPrivateKey", "ParameterValue": anode.privatekey } )
            data.append(   { "ParameterKey":"Server1PuppetCertMyCert", "ParameterValue": anode.cert } )

        # 2. pk (hack - todo readin the json...)
        if anode.name.count('2') > 0: 
            data.append(   { "ParameterKey":"Server2Name", "ParameterValue": anode.name } )
            data.append(   { "ParameterKey":"Server2PuppetCertMyPrivateKey", "ParameterValue": anode.privatekey } )
            data.append(   { "ParameterKey":"Server2PuppetCertMyCert", "ParameterValue": anode.cert } )


    #print json.dumps( data, sort_keys=True,indent=4)
    print 'writing out json param file: ' + lofile
    wf = open( lofile, 'w')
    wf.write( json.dumps( data, sort_keys=True,indent=4) )
    wf.close()
    return(0)



# "list" of nodes
AllNodes = dict()

# process command line
if len(sys.argv) < 3:
    usage()

if len( sys.argv[1] ) > 0:
    NAME=sys.argv[1]
    INPARAMS=NAME + "inparms.json"
else:
    error('please provide the stack name')

if ( os.path.isfile( sys.argv[2] ) ):
    STACKTEMPLATE=sys.argv[2]
else:
    error('please provide the JSON stack template filename')

for i in range(3,len(sys.argv) ):
    anode = ANode( sys.argv[i] )
    AllNodes[ anode ] = anode

# check the [<webserver names>] are in site.pp { site standard }
CheckSitepp( AllNodes )

# check/generate if required the puppet certs - grabbing filenames as we go
DoPuppetCerts( AllNodes )

# validate the template 
RunCommandFore("aws cloudformation validate-template --template-body file:///" + os.getcwd() + "/" + STACKTEMPLATE )

# write out the json parm file
WriteJSONParmFile( INPARAMS, AllNodes )

#sys.exit(0)

# execute the template build
RunCommandFore("aws cloudformation create-stack --stack-name=" + NAME +" --template-body file:///" + os.getcwd() + "/" + STACKTEMPLATE + " --parameters file:///" + os.getcwd() + "/" + INPARAMS )
