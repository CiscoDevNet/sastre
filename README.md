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

One of the following tasks can be specified: backup, restore, delete or list. Adding -h after the task displays help on the additional arguments for the specified task.

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

Dry-run, just list the items matching the specified tag and regular expression:

    ./sastre.py --verbose delete all --regex "VPN1" --dryrun
    INFO: Starting delete task: vManage URL: "https://10.85.136.253:8443"
    INFO: Inspecting template_device items
    INFO: Inspecting template_feature items
    INFO: DRY-RUN: feature template VPN1_Interface5_v01
    <snip>
    INFO: Delete task complete
    
Deleting items:

    ./sastre.py --verbose delete all --regex "VPN1"
    INFO: Starting delete task: vManage URL: "https://10.85.136.253:8443"
    INFO: Inspecting template_device items
    INFO: Inspecting template_feature items
    INFO: Done feature template VPN1_Interface5_v01
    <snip>
    INFO: Delete task complete
    
### List items from vManage or from backup:

The list task can be used to list items from a target vManage, or a backup directory, matching a criteria of item tag(s) and regular expression.

List device templates and feature templates from target vManage:

    ./sastre.py --verbose list template_device template_feature
    INFO: Starting list task: vManage URL: "https://10.85.136.253:8443"
    INFO: List criteria matched 355 items
    +------------------+--------------------------------------------------------------------+--------------------------------------+------------------+
    | Tag              | Name                                                               | ID                                   | Description      |
    +------------------+--------------------------------------------------------------------+--------------------------------------+------------------+
    | template_device  | BRANCH_ADVANCED                                                    | 61b3b608-8ce5-4f9a-bdb2-7d23f759cd9f | device template  |
    <snip>
    | template_feature | VPN1_Interface1_v01                                                | 3768c2b8-65cb-4306-a1a7-f345ed789758 | feature template |
    | template_feature | VPN0_Parent_Interface2_v01                                         | e5db93c7-ffd6-45eb-bbd4-29caab0f3d70 | feature template |
    +------------------+--------------------------------------------------------------------+--------------------------------------+------------------+
    INFO: List task completed successfully    
 
 List all items from target vManage with name starting with 'DC':
 
     ./sastre.py list all --regex "^DC"
    +-------------------+------------------+--------------------------------------+---------------------------+
    | Tag               | Name             | ID                                   | Description               |
    +-------------------+------------------+--------------------------------------+---------------------------+
    | template_device   | DC_BASIC         | 64fc7226-2047-4fee-8460-a6df30ed7479 | device template           |
    | template_device   | DC_ADVANCED      | 68bdd855-2c26-40ea-8c39-b50bf5bcebe4 | device template           |
    | policy_definition | DC_Reject_DC_Out | 26b8bb45-6191-4a71-828f-b1d2d0a6ecff | control policy definition |
    | policy_list       | DC_All           | d9b1f339-c914-4f0c-a2c3-610b4f6e6c2d | site list                 |
    +-------------------+------------------+--------------------------------------+---------------------------+

List all items from backup directory with name starting with 'DC':

    ./sastre.py --verbose list all --regex "^DC" --workdir node_10.85.136.253_02072019
    INFO: Starting list task: Work_dir: "node_10.85.136.253_02072019"
    INFO: List criteria matched 2 items
    +-----------------+-------------+--------------------------------------+-----------------+
    | Tag             | Name        | ID                                   | Description     |
    +-----------------+-------------+--------------------------------------+-----------------+
    | template_device | DC_ADVANCED | 8845bbdd-31c3-4fd7-b3c3-17fe13c1fcb4 | device template |
    | template_device | DC_BASIC    | 1cd6a025-a7e8-48e8-8757-dc00de06e4b9 | device template |
    +-----------------+-------------+--------------------------------------+-----------------+
    INFO: List task completed successfully

## Regular Expressions

It is recommended to always use double quotes when specifying a regular expression to --regex option:

    ./sastre.py --verbose restore all --regex "VPN1"
     
This is to prevent the shell from interpreting special characters that could be part of the pattern provided.

Matching done by the --regex is un-anchored. That is, unless anchor marks are provided (e.g. ^ or $), the pattern matches if present anywhere in the string. In other words, this is a search function.

The regular expression syntax is described here: https://docs.python.org/3/library/re.html

## Logs

Sastre logs messages to the terminal and to log files (under the logs directory).

Debug-level and higher severity messages are always saved to the log files.

The --verbose flag controls the severity of messages printed to the terminal. If --verbose is not specified, only warning-level and higher messages are logged. When --verbose is specified, informational-level and higher messages are printed. 

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
