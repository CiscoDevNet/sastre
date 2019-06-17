# Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

Sastre provides utility functions to assist with managing configuration elements in vManage. This includes backup, restore and delete vManage configuration items.

## Requirements

Sastre requires Python 3.6 or newer and the requests pip package.

This can be verified by pasting the following in a terminal window:

    python3 -c "import requests;import sys;assert sys.version_info>(3,6)" && echo "ALL GOOD"
    
If 'ALL GOOD' is printed it means all requirements are met. Otherwise additional installation steps are required. Specific instructions on how to install those requirements on different OSs are provided at the end, in the 'Installing Requirements' section.

## Usage
 
Sastre has a set of basic options as well as task-specific arguments.
 
The general command line structure is as follows:
 
    sastre.py [-h] [-a <vmanage-ip>] [-u <user>] [-p <password>]
                   [--port [<port>]] [--timeout [<timeout>]] [--verbose]
                   [--version]
                   <task> ...
 
The vManage address (-a), username (-u) and password (-p) can also be provided via environmental variables:
- VMANAGE_IP
- VMANAGE_USER
- VMANAGE_PASSWORD

The 'sastre-rc-example.sh' file is provided as an example of a file that can be sourced to set those variables.

One of the following tasks can be specified: backup, restore or delete. Adding -h after the task displays help on the additional arguments for the specified task.

Important concepts:
- vManage URL: Built from the provided vManage IP address and TCP port (default 8443). All operations target this vManage.
- Work dir: Defines the location (in the local machine) where vManage data files are located. By default it follows the format "node_<vmanage-ip>". With the restore task, the --workdir parameter can be used to provide the location of data files to be used. This scenario is used to transfer data files from one vManage to another. Workdir is under the 'data' directory. 
- Tag: vManage configuration items are grouped by tags, such as policy_apply, policy_definition, policy_list, template_device, etc. The special tag 'all' is used to refer to all configuration elements. Depending on the task, one or more tags can be specified in order to select specific configuration elements.

## Examples

Go to the directory where the Sastre package was extracted:

    cd sastre

Edit sastre-rc-example.sh to include vManage details and source that file:

    cat sastre-rc-example.sh 
     export VMANAGE_IP='10.11.12.13'
     export VMANAGE_USER='admin'
     export VMANAGE_PASSWORD='admin'
    
    source sastre-rc-example.sh

### Backup vManage:

    ./sastre.py --verbose backup all
    INFO: Starting backup task: vManage URL: "https://10.85.136.253:8443" > Work_dir: "node_10.85.136.253"
    <snip>
    INFO: Backup task complete

### Restore to the same vMmanage:

     ./sastre.py --verbose restore all
    INFO: Starting restore task: Work_dir: "node_10.85.136.253" > vManage URL: "https://10.85.136.253:8443"
    <snip>
    INFO: Restore task complete

### Restore files that were backed-up from a different vManage:

    ./sastre.py --verbose restore all --workdir node_10.200.200.8
    INFO: Starting restore task: Work_dir: "node_10.200.200.8" > vManage URL: "https://10.85.136.253:8443"
    <snip>
    INFO: Restore task complete

### Delete templates from vManage:

Just list the items matching the specified tag and regular expression:

    ./sastre.py --verbose delete all --regexp "VPN1.*" --dryrun
    INFO: Starting delete task: vManage URL: "https://10.85.136.253:8443"
    INFO: Inspecting template_device items
    INFO: Inspecting template_feature items
    INFO: DRY-RUN: feature template VPN1_Interface5_v01
    <snip>
    INFO: Delete task complete
    
Deleting items:

    ./sastre.py --verbose delete all --regexp "VPN1.*"
    INFO: Starting delete task: vManage URL: "https://10.85.136.253:8443"
    INFO: Inspecting template_device items
    INFO: Inspecting template_feature items
    INFO: Done feature template VPN1_Interface5_v01
    <snip>
    INFO: Delete task complete

## Installing Requirements

### Ubuntu 18.04 LTS/Bionic

Install distutils:

    sudo apt-get install python3-distutils

Install pip3:
    
    curl -O https://bootstrap.pypa.io/get-pip.py
    sudo python3 get-pip.py

Install required pip3 packages:
    
    sudo pip3 install --upgrade requests
    
    
### MacOS 10.14/Mojave
 
Install Python3:
- Look for the latest 3.x.x version at Python.org: https://www.python.org/downloads/

Install required pip3 packages:
    
    pip3 install --upgrade requests
