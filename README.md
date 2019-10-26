[![published](https://static.production.devnetcloud.com/codeexchange/assets/images/devnet-published.svg)](https://developer.cisco.com/codeexchange/github/repo/reismarcelo/sastre)

# Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

Sastre provides utility functions to assist with managing configuration elements in vManage. This includes backup, restore and delete vManage configuration items.

## Important note on backup format changes in v0.30

The backup database format was changed in Sastre 0.30. Backups taken with previous releases cannot be restored using the new release. Please check the CHANGES file for further details.

The latest release using the old backup format was tagged as 'v0.2'. If there is a need to use older backups, just git checkout this tag:

    git checkout v0.2

In order to return to the latest release:

    git checkout master

## Requirements

Sastre requires Python 3.6 or newer and the requests pip package.

This can be verified by pasting the following in a terminal window:

    python3 -c "import requests;import sys;assert sys.version_info>(3,6)" && echo "ALL GOOD"
    
If 'ALL GOOD' is printed it means all requirements are met. Otherwise additional installation steps are required. Specific instructions on how to install those requirements on different OSs are provided at the end, in the 'Installing Requirements' section.

## Usage
 
Sastre has a set of basic options as well as task-specific arguments.
 
The general command line structure is as follows:

     sastre.py [-h] [-a <vmanage-ip>] [-u <user>] [-p <password>]
                 [--port <port>] [--timeout <timeout>] [--verbose] [--version]
                 <task> ...

The vManage address (-a), username (-u) and password (-p) can also be provided via environmental variables:
- VMANAGE_IP
- VMANAGE_USER
- VMANAGE_PASSWORD

The 'sastre-rc-example.sh' file is provided as an example of a file that can be sourced to set those variables.

Tasks currently available: backup, restore, delete, list or show-template. Adding -h after the task displays help on the additional arguments for the specified task.

Task-specific parameters and options (including help) are provided after the task:

    ./sastre.py --verbose backup --help
    usage: sastre.py backup [-h] [--workdir <directory>] <tag> [<tag> ...]
    
    Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela
    
    Backup task:
    
    positional arguments:
      <tag>                 One or more tags for selecting items to be backed up.
                            Multiple tags should be separated by space. Available
                            tags: all, policy_definition, policy_list,
                            policy_security, policy_vedge, policy_vsmart,
                            template_device, template_feature. Special tag 'all'
                            selects all items.
    
    optional arguments:
      -h, --help            show this help message and exit
      --workdir <directory>
                            Directory used to save the backup (default will be
                            "backup_10.85.136.253_20191004").

Important concepts:
- vManage URL: Built from the provided vManage IP address and TCP port (default 8443). All operations target this vManage.
- Workdir: Defines the location (in the local machine) where vManage data files are located. By default it follows the format "backup_\<vmanage-ip\>_\<yyyymmdd\>". With the restore task, the --workdir parameter can be used to provide the location of data files to be used. This scenario is used to transfer data files from one vManage to another. Workdir is under the 'data' directory. 
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
    INFO: Starting backup: vManage URL: "https://10.85.136.253:8443" > Local workdir: "backup_10.85.136.253_20191004"
    <snip>
    INFO: Task completed successfully

#### Customize backup directory:

    ./sastre.py --verbose backup all --workdir "my_custom_directory"
    INFO: Starting backup: vManage URL: "https://10.85.136.253:8443" > Local workdir: "my_custom_directory"
    <snip>
    INFO: Task completed successfully

### Restore vMmanage:

    ./sastre.py --verbose restore all
    INFO: Starting restore: Local workdir: "backup_10.85.136.253_20191004" > vManage URL: "https://10.85.136.253:8443"
    INFO: Loading existing items from target vManage
    INFO: Identifying items to be pushed
    INFO: Inspecting template_device items
    INFO: Inspecting template_feature items
    INFO: Inspecting policy_vsmart items
    INFO: Inspecting policy_vedge items
    INFO: Inspecting policy_security items
    INFO: Inspecting policy_definition items
    INFO: Inspecting policy_list items
    INFO: Pushing items to vManage
    INFO: Done: Create SLA-class list Best_Effort
    <snip>
    INFO: Task completed successfully
    
#### Including template attachments and policy activation with the restore:
    
    ./sastre.py --verbose restore all --attach
    INFO: Starting restore: Local workdir: "backup_10.85.136.253_20191004" > vManage URL: "https://10.85.136.253:8443"
    <snip>
    INFO: Done: Create device template BRANCH_BASIC
    INFO: Attaching WAN Edge templates
    INFO: Waiting...
    INFO: Completed DC_BASIC,BRANCH_BASIC
    INFO: Completed attaching WAN Edge templates
    INFO: Attaching vSmart template
    INFO: Waiting...
    INFO: Completed VSMART_v1
    INFO: Completed attaching vSmart template
    INFO: Activating vSmart policy
    INFO: Waiting...
    INFO: Completed Central_policy_v1
    INFO: Completed activating vSmart policy
    INFO: Task completed successfully

#### Overwriting items with the --force option:
- By default, when an item from backup has the same name as an existing item in vManage, restore will skip this item and leave the existing one intact.
- When an item, say a device template, is modified in vManage. Performing a restore from a backup taken before the modification will skip that item.
- With the --force option, items with the same name are updated with the info found in the backup.
- Sastre only tries to update when the item payload is actually different.
- If the item is associated with attached templates or activated policies, all necessary re-attach/re-activate actions are automatically performed.
- Currently, the --force option does not apply to changes in template values. 

Example:

    ./sastre.py --verbose restore all --workdir state_b --force
    INFO: Starting restore: Local workdir: "state_b" > vManage URL: "https://10.85.136.253:8443"
    INFO: Loading existing items from target vManage
    INFO: Identifying items to be pushed
    INFO: Inspecting template_device items
    INFO: Inspecting template_feature items
    INFO: Inspecting policy_vsmart items
    INFO: Inspecting policy_vedge items
    INFO: Inspecting policy_security items
    INFO: Inspecting policy_definition items
    INFO: Inspecting policy_list items
    INFO: Pushing items to vManage
    INFO: Done: Create community list LOCAL_DC_PREFIXES
    INFO: Done: Create community list REMAINING_PREFIXES
    INFO: Updating SLA-class list Best_Effort requires reattach of affected templates
    INFO: Reattaching templates
    INFO: Waiting...
    INFO: Waiting...
    INFO: Completed VSMART_v1
    INFO: Completed reattaching templates
    INFO: Done: Update SLA-class list Best_Effort
    <snip>
    INFO: Done: Update device template DC_BASIC
    INFO: Task completed successfully

#### Specifying a different directory to source from:

    ./sastre.py --verbose restore all --workdir node_10.85.136.253_22082019
    INFO: Starting restore: Local workdir: "node_10.85.136.253_22082019" > vManage URL: "https://10.85.136.253:8443"
    INFO: Loading existing items from target vManage
    <snip>
    INFO: Task completed successfully

### Delete templates from vManage:

Dry-run, just list the items matching the specified tag and regular expression:

    ./sastre.py --verbose delete all --regex "VPN1" --dryrun
    INFO: Starting delete, DRY-RUN mode: vManage URL: "https://10.85.136.253:8443"
    INFO: Inspecting template_device items
    INFO: Inspecting template_feature items
    INFO: DRY-RUN: Delete feature template VPN1_Interface4_v01
    <snip>
    INFO: Task completed successfully
    
Deleting items:

    ./sastre.py --verbose delete all --regex "VPN1"
    INFO: Starting delete: vManage URL: "https://10.85.136.253:8443"
    INFO: Inspecting template_device items
    INFO: Inspecting template_feature items
    INFO: Done: Delete feature template VPN1_Interface4_v01
    <snip>
    INFO: Task completed successfully

    
#### Delete with detach:
- When vSmart policies are activated and device templates are attached, the associated items cannot be deleted. 
- The --detach option performs the necessary template detach and vSmart policy deactivate before proceeding with the delete.

Example:

    ./sastre.py --verbose delete all --detach
    INFO: Starting delete: vManage URL: "https://10.85.136.253:8443"
    INFO: Detaching WAN Edge templates
    INFO: Waiting...
    INFO: Completed BRANCH_BASIC
    INFO: Completed DC_BASIC
    INFO: Completed detaching WAN Edge templates
    INFO: Deactivating vSmart policy
    INFO: Waiting...
    INFO: Completed Central_policy_v1
    INFO: Completed deactivating vSmart policy
    INFO: Detaching vSmart template
    INFO: Waiting...
    INFO: Completed VSMART_v1
    INFO: Completed detaching vSmart template
    INFO: Inspecting template_device items
    INFO: Done: Delete device template vManage_template
    <snip>
    INFO: Task completed successfully

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

### Show items from vManage or from backup

Similarly to list, show tasks can be used to show items from a target vManage, or a backup directory. With show tasks, additional details about the selected items are displayed. The item id, name or a regular expression can be used to identify which item(s) to display.

     ./sastre.py show-template values --name DC_BASIC
    Device template DC_BASIC, values for vedge-dc1:
    +-----------------------------------+--------------------------------------+--------------------------------------------------------------------+
    | Name                              | Value                                | Variable                                                           |
    +-----------------------------------+--------------------------------------+--------------------------------------------------------------------+
    | Status                            | complete                             | csv-status                                                         |
    | Chassis Number                    | b693be59-c03f-62d0-f9a4-2675374536b8 | csv-deviceId                                                       |
    | System IP                         | 10.255.101.1                         | csv-deviceIP                                                       |
    | Hostname                          | vedge-dc1                            | csv-host-name                                                      |
    | Hostname(system_host_name)        | vedge-dc1                            | //system/host-name                                                 |
    | System IP(system_system_ip)       | 10.255.101.1                         | //system/system-ip                                                 |
    | Site ID(system_site_id)           | 101                                  | //system/site-id                                                   |
    | IPv4 Address(vpn_if_ipv4_address) | 10.101.1.4/24                        | /10/ge0/2/interface/ip/address                                     |
    | IPv4 Address(vpn_if_ipv4_address) | 5.254.4.110/24                       | /20/ge0/3/interface/ip/address                                     |
    | AS Number(bgp_as_num)             | 65001                                | /20//router/bgp/as-num                                             |
    | Address(bgp_neighbor_address)     | 5.254.4.1                            | /20//router/bgp/neighbor/bgp_neighbor_address/address              |
    | Remote AS(bgp_neighbor_remote_as) | 65111                                | /20//router/bgp/neighbor/bgp_neighbor_address/remote-as            |
    | Preference(transport1_preference) | 100                                  | /0/ge0/0/interface/tunnel-interface/encapsulation/ipsec/preference |
    +-----------------------------------+--------------------------------------+--------------------------------------------------------------------+
    
    Device template DC_BASIC, values for vedge-dc2:
    +-----------------------------------+--------------------------------------+--------------------------------------------------------------------+
    | Name                              | Value                                | Variable                                                           |
    +-----------------------------------+--------------------------------------+--------------------------------------------------------------------+
    | Status                            | complete                             | csv-status                                                         |
    | Chassis Number                    | 0dd49ace-f6de-ce86-5d73-ca74d6db1747 | csv-deviceId                                                       |
    | System IP                         | 10.255.102.1                         | csv-deviceIP                                                       |
    | Hostname                          | vedge-dc2                            | csv-host-name                                                      |
    | Hostname(system_host_name)        | vedge-dc2                            | //system/host-name                                                 |
    | System IP(system_system_ip)       | 10.255.102.1                         | //system/system-ip                                                 |
    | Site ID(system_site_id)           | 102                                  | //system/site-id                                                   |
    | IPv4 Address(vpn_if_ipv4_address) | 10.102.1.3/24                        | /10/ge0/2/interface/ip/address                                     |
    | IPv4 Address(vpn_if_ipv4_address) | 5.254.5.105/24                       | /20/ge0/3/interface/ip/address                                     |
    | AS Number(bgp_as_num)             | 65002                                | /20//router/bgp/as-num                                             |
    | Address(bgp_neighbor_address)     | 5.254.5.1                            | /20//router/bgp/neighbor/bgp_neighbor_address/address              |
    | Remote AS(bgp_neighbor_remote_as) | 65222                                | /20//router/bgp/neighbor/bgp_neighbor_address/remote-as            |
    | Preference(transport1_preference) | 0                                    | /0/ge0/0/interface/tunnel-interface/encapsulation/ipsec/preference |
    +-----------------------------------+--------------------------------------+--------------------------------------------------------------------+


## Notes

### Regular Expressions

It is recommended to always use double quotes when specifying a regular expression to --regex option:

    ./sastre.py --verbose restore all --regex "VPN1"
     
This is to prevent the shell from interpreting special characters that could be part of the pattern provided.

Matching done by the --regex is un-anchored. That is, unless anchor marks are provided (e.g. ^ or $), the pattern matches if present anywhere in the string. In other words, this is a search function.

The regular expression syntax is described here: https://docs.python.org/3/library/re.html

### Logs

Sastre logs messages to the terminal and to log files (under the logs directory).

Debug-level and higher severity messages are always saved to the log files.

The --verbose flag controls the severity of messages printed to the terminal. If --verbose is not specified, only warning-level and higher messages are logged. When --verbose is specified, informational-level and higher messages are printed. 

### Restore behavior

By default restore will skip items with the same name. If an existing item in vManage has the same name as an item in the backup, this item is skipped from restore. Any references/dependencies on that item are properly updated. For instanve, if a feature template is not pushed to vManage because an item with the sama name is already present. Device templates being pushed will now point to the feature template which was already in vManage.

Adding the --force option to restore modifies the default behavior. In this case Sastre will update existing items containing the same name as in the backup if their content is different. 

When an existing vManage item is modified, device templates may need to be reattached or vSmart policies may need to be re-activated. This is handled by Sastre as follows:
- On updates to a master template (e.g. device template) containing attached devices, Sastre will re-attach this device template using attachment values (variables) from the backup to feed the attach request.
- On Updates to a child template (e.g. feature template) associated with a master template containing attached devices, Sastre will re-attach the affected master template(s). In this case, Sastre will use the existing values in vManage to feed the attach request.
- The implication is that if the modified child template (e.g. feature template) defines new variables, re-attaching its master template will fail because not all variables will have values assigned. In this case, the recommended procedure is to detach the master template (i.e. change device to CLI mode in vManage), re-run the restore --force task and then re-attach the device-template from vManage, where one would have a chance to supply all missing variable values.
- Updating items associated with an active vSmart policy may require this policy to be re-activated. In this case, Sastre will request the policy reactivate as well.


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
