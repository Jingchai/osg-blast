#!/usr/bin/python

import sys
import os
import time
import shutil
import urllib
import re

if len(sys.argv) != 7:
    print "#arg: project_name db queries blast_type \"blast_opt\""
    sys.exit(1)

project=sys.argv[1]
dbname=sys.argv[2]
dbver=sys.argv[3]
query_path=sys.argv[4]
blast_type=sys.argv[5]
user_blast_opt=sys.argv[6]

block_size=412 #adjust this so that most job will run for 1 - 2 hours

#blast_bin = "/N/soft/rhel6/ncbi-blast+/2.2.28/bin" #doesn't work -- executable compiled using locally available libs
#blast_bin = "/N/u/iugalaxy/Mason/soichi/ncbi-blast-2.2.28+/bin"

#blast_bin = "/usr/local/ncbi-blast-2.2.28+/bin"
#db_dir = "/local-scratch/public_html/hayashis/blastdb/"+dbname+"."+dbver
db_path = "http://osg-xsede.grid.iu.edu/scratch/iugalaxy/blastdb/"+dbname+"."+dbver
bin_path = "http://osg-xsede.grid.iu.edu/scratch/iugalaxy/blastapp/ncbi-blast-2.2.28+/bin"
rundir = "/N/dcwan/scratch/iugalaxy/rundir/"+str(time.time())

#create rundir
if os.path.exists(rundir):
    print "#rundir already exists.."
    sys.exit(1)
else:
    os.makedirs(rundir)
os.mkdir(rundir+"/log")
os.mkdir(rundir+"/output")

#parse input query
input = open(query_path)
queries = []
query = ""
name = ""
for line in input.readlines():
    if line[0] == ">":
        if name != "":
            queries.append([name, query])
        name = line
        query = ""
    else:
        query += line
if name != "":
    queries.append([name, query])
input.close()

#split queries into blocks
inputdir=rundir+"/input"
os.makedirs(inputdir)
block = {}
count = 0
block = 0
for query in queries:
    if count == 0:
        if block != 0:
            outfile.close() 
        outfile = open("%s/block_%d" % (inputdir, block), "w")
        block+=1
    count+=1
    if count == block_size:
        count = 0

    outfile.write(query[0])
    outfile.write(query[1])
if outfile:
    outfile.close()

#list *.gz on the db_path
con = urllib.urlopen(db_path+"/list")
html = con.read()
con.close()
dbparts = []
for part in html.split("\n"):
    if part == "": 
        continue
    dbparts.append(part)

#print "#number of db parts", len(dbparts)

#I don't know how to pass double quote escaped arguments via condor arguemnts option
#so let's pass via writing out to file.
#we need to concat user blast opt to db blast opt
con = urllib.urlopen(db_path+"/blast.opt")
db_blast_opt = con.read().strip()
con.close()
blast_opt = file(rundir+"/blast.opt", "w")
blast_opt.write(db_blast_opt)
blast_opt.write(" "+user_blast_opt)

#500 will cause memory usage issue with merge.py
#TODO - update on merge.py as well to match this (should be configurable..)
blast_opt.write(" -max_target_seqs 20") 

blast_opt.close()

#output condor submit file for running blast
dag = open(rundir+"/blast.dag", "w")
for query_block in os.listdir(inputdir):

    sub_name = query_block+".sub"
    sub = open(rundir+"/"+sub_name, "w")
    #sub.write("universe = vanilla\n") #for osg-xsede
    sub.write("universe = grid\n") #on bosco submit node (soichi6)
    sub.write("notification = never\n")
    sub.write("ShouldTransferFiles = YES\n")
    sub.write("when_to_transfer_output = ON_EXIT\n\n")

    #not sure if this helps or not..
    #sub.write("request_memory = 500\n\n") #in megabytes
    #sub.write("request_disk = 256000\n\n") #in kilobytes

    #per derek.. to restart long running jobs .. 412 queries should be process in 20-30 minutes range (sometimes 50min..) kill at 60 minutes
    sub.write("periodic_hold = ( ( CurrentTime - EnteredCurrentStatus ) > 3600) && JobStatus == 2\n") 
    sub.write("periodic_release = ( ( CurrentTime - EnteredCurrentStatus ) > 30 )\n") #release after 30 seconds
    sub.write("on_exit_hold = (ExitBySignal == True) || (ExitCode != 0)\n") #stay in queue on failures

    #sub.write("periodic_remove = (CommittedTime - CommittedSuspensionTime) > 7200\n") #not sure if this works

    #sub.write("periodic_remove = (ServerTime - JobCurrentStartDate) >= 7200\n") #not sure if this works
    #above doesn't work... seem to be killing jobs left and right, and.. also seeing following
    #012 (38534006.002.000) 08/31 13:29:19 Job was held.
    #    The job attribute PeriodicRemove expression '( ServerTime - JobCurrentStartDate ) >= 7200' evaluated to UNDEFINED
    #    Code 5 Subcode 0

    sub.write("executable = blast_wrapper.sh\n")
    sub.write("output = log/"+query_block+".part_$(Process).out\n")
    sub.write("error = log/"+query_block+".part_$(Process).err\n")
    sub.write("log = log/"+query_block+".log\n")
    sub.write("+ProjectName = \""+project+"\"\n") #only works if submitted directly on osg-xsede (use ~/.xsede_default_project instead)
    sub.write("transfer_output_files = output\n");

    #TODO - I should probably compress blast executable and input query block?
    sub.write("transfer_input_files = blast.opt,input/"+query_block+"\n")
    sub.write("arguments = "+bin_path+" "+blast_type+" "+query_block+" "+dbname+" "+db_path+" $(Process) output/"+query_block+".part_$(Process).result\n\n");

    sub.write("queue "+str(len(dbparts))+"\n")
    sub.close()

    #copy blast_wrapper.sh
    shutil.copy("blast_wrapper.sh", rundir)

    #copy merge.py
    shutil.copy("merge.py", rundir)

    msub_name = query_block+".merge.sub"
    msub = open(rundir+"/"+msub_name, "w")
    msub.write("universe = local\n")
    msub.write("notification = never\n")
    msub.write("executable = merge.py\n")
    msub.write("arguments = "+query_block+"\n")
    msub.write("output = log/"+query_block+".merge.out\n")
    msub.write("error = log/"+query_block+".merge.err\n")
    msub.write("log = log/"+query_block+".merge.log\n")
    msub.write("queue\n")

    dag.write("JOB "+query_block+" "+sub_name+"\n")
    dag.write("RETRY "+query_block+" 10\n")
    dag.write("JOB "+query_block+".merge "+msub_name+"\n")
    dag.write("PARENT "+query_block+" CHILD "+query_block+".merge\n")
    dag.write("RETRY "+query_block+" 3\n")

dag.close()

#output rundir
print rundir
