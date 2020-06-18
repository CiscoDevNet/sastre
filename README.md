[![published](https://static.production.devnetcloud.com/codeexchange/assets/images/devnet-published.svg)](https://developer.cisco.com/codeexchange/github/repo/reismarcelo/sastre)

# Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

Sastre provides functions to assist with managing configuration elements in Cisco vManage, including backup, restore and delete tasks.

## Introduction
 
Sastre has a set of base parameters as well as task-specific arguments. 

The command line is structured as follows:

    sdwan <base parameters> <task> <task-specific parameters>

Currently available tasks: 
- Backup: Save vManage configuration items to a local backup.
- Restore: Restore configuration items from a local backup to vManage.
- Delete: Delete configuration items on vManage.
- Certificate: Restore device certificate validity status from a backup or set to a desired value (i.e. valid, invalid or staging).
- List: List configuration items or device certificate information from vManage or a local backup. Display as table or export as csv file.
- Show-template: Show details about device templates on vManage or from a local backup. Display as table or export as csv file.
- Migrate: Migrate configuration items from a vManage release to another. Currently only 18.4, 19.2 or 19.3 to 20.1 is supported. Minor revision numbers (e.g. 20.1.1) are not relevant for the template migration.

Notes:
- Either 'sdwan' or 'sastre' can be used as the main command.
- The command line described above, and in all examples that follow, assume Sastre was installed from PyPI, via PIP. 
- If Sastre was download from GitHub, then 'sdwan.py' or 'sastre.py' should used instead. Please check the installation section for more details.

### Base parameters

    % sdwan -h
    usage: sdwan [-h] [-a <vmanage-ip>] [-u <user>] [-p <password>] [--port <port>] [--timeout <timeout>] [--verbose] [--version] <task> ...
    
    Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela
    
    positional arguments:
      <task>                task to be performed (backup, restore, delete, certificate, list, show-template, migrate)
      <arguments>           task parameters, if any
    
    optional arguments:
      -h, --help            show this help message and exit
      -a <vmanage-ip>, --address <vmanage-ip>
                            vManage IP address, can also be defined via VMANAGE_IP environment variable. If neither is provided user is prompted for the address.
      -u <user>, --user <user>
                            username, can also be defined via VMANAGE_USER environment variable. If neither is provided user is prompted for username.
      -p <password>, --password <password>
                            password, can also be defined via VMANAGE_PASSWORD environment variable. If neither is provided user is prompted for password.
      --port <port>         vManage TCP port number (default: 8443)
      --timeout <timeout>   REST API timeout (default: 300)
      --verbose             increase output verbosity
      --version             show program's version number and exit

vManage address (-a/--address), user name (-u/--user) and password (-p/--password) can also be provided via environment variables:
- VMANAGE_IP
- VMANAGE_USER
- VMANAGE_PASSWORD

A good approach to reduce the number of parameters that need to be provided at execution is to create rc text files exporting those environment variables for a particular vManage. This is demonstrated in the Getting Started section below.

For any of these arguments, vManage address, user and password; user is prompted for a value if they are not provided via the environment variables or command line arguments.

### Task-specific parameters

Task-specific parameters and options are defined after the task is provided. Each task has its own set of parameters.

    % sdwan backup -h
    usage: sdwan backup [-h] [--workdir <directory>] [--no-rollover] [--regex <regex>] <tag> [<tag> ...]
    
    Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela
    
    Backup task:
    
    positional arguments:
      <tag>                 One or more tags for selecting items to be backed up. Multiple tags should be separated by space. Available tags: all, policy_customapp,
                            policy_definition, policy_list, policy_profile, policy_security, policy_vedge, policy_voice, policy_vsmart, template_device, template_feature. Special
                            tag "all" selects all items, including WAN edge certificates and device configurations.
    
    optional arguments:
      -h, --help            show this help message and exit
      --workdir <directory>
                            Backup destination (default: backup_VMANAGE-ADDRESS_20200617).
      --no-rollover         By default, if workdir already exists (before a new backup is saved) the old workdir is renamed using a rolling naming scheme. This option disables
                            this automatic rollover.
      --regex <regex>       Regular expression matching item names to be backed up, within selected tags.

#### Important concepts:
- vManage URL: Built from the provided vManage IP address and TCP port (default 8443). All operations target this vManage.
- Workdir: Defines the location (in the local machine) where vManage data files are located. By default it follows the format "backup_\<vmanage-ip\>_\<yyyymmdd\>". The --workdir parameter can be used to specify a different location.  Workdir is under a 'data' directory. This 'data' directory is relative to the directory where Sastre is run.
- Tag: vManage configuration items are grouped by tags, such as policy_apply, policy_definition, policy_list, template_device, etc. The special tag 'all' is used to refer to all configuration elements. Depending on the task, one or more tags can be specified in order to select groups of configuration elements.

## Getting Started

Create a directory to serve as root for backup files, log files and rc files:

    % mkdir sastre
    % cd sastre
    
When Sastre is executed, data/ and logs/ directories are created as needed to store backup files and application logs. These are created under the directory where Sastre is run.

Create an rc-example.sh file to include vManage details and source that file:

    % cat <<EOF > rc-example.sh
     export VMANAGE_IP='10.85.136.253'
     export VMANAGE_USER='admin'
    EOF
    % source rc-example.sh

Note that in this example the password was not defined, the user will be prompted for a password.

Test vManage credentials by running a simple query listing configured device templates:

    % sdwan list configuration template_device
    vManage password: 
    +-----------------+--------------------------------------+-----------------+-----------------+
    | Name            | ID                                   | Tag             | Type            |
    +-----------------+--------------------------------------+-----------------+-----------------+
    | DC_ADVANCED     | bf322748-8dfd-4cb0-a9e4-5d758be239a0 | template_device | device template |
    | DC_BASIC        | 09c02518-9557-4ae2-9031-7e6b3e7323fc | template_device | device template |
    | VSMART_v1       | 15c1962f-740e-4b89-a269-69f2cbfba296 | template_device | device template |
    | BRANCH_ADVANCED | ad449106-7ed6-442f-9ba8-820612b85981 | template_device | device template |
    | BRANCH_BASIC    | cc2f7a24-4c93-49ed-8e6b-1c107797ba95 | template_device | device template |
    +-----------------+--------------------------------------+-----------------+-----------------+

Any those vManage parameters can also be provided via command line:

    % sdwan -p admin list configuration template_device

Perform a backup:

    % sdwan --verbose backup all
    INFO: Starting backup: vManage URL: "https://10.85.136.253:8443" -> Local workdir: "backup_10.85.136.253_20200617"
    INFO: Saved vManage server information
    INFO: Saved WAN edge certificates
    INFO: Done device configuration vedge-dc1
    INFO: Done device configuration vedge-dc2
    INFO: Done device configuration vedge-b1
    INFO: Done device configuration vedge-b2
    INFO: Done device configuration vmanage-1
    INFO: Done device configuration vsmart-1
    INFO: Done device configuration vbond-1
    INFO: Saved device template index
    INFO: Done device template DC_ADVANCED
    INFO: Done device template DC_BASIC
    INFO: Done device template DC_BASIC attached devices
    INFO: Done device template DC_BASIC values
    <snip>
    INFO: Done SLA-class list Realtime_Full_Mesh
    INFO: Task completed successfully
    
Note that '--verbose' was specified so that progress information is displayed. Without this option, only warning-level messages and above are displayed.

The backup is saved under data/backup_10.85.136.253_20191206:

    % ls
    data		logs		rc-example.sh
    % ls data
    backup_10.85.136.253_20191206

## Additional Examples

### Customizing backup destination:

    % sdwan --verbose backup all --workdir "my_custom_directory"
    INFO: Starting backup: vManage URL: "https://10.85.136.253:8443" -> Local workdir: "my_custom_directory"
    INFO: Saved vManage server information
    INFO: Saved WAN edge certificates
    INFO: Done device configuration vedge-dc1
    INFO: Done device configuration vedge-dc2
    INFO: Done device configuration vedge-b1
    INFO: Done device configuration vedge-b2
    INFO: Done device configuration vmanage-1
    INFO: Done device configuration vsmart-1
    INFO: Done device configuration vbond-1
    INFO: Saved device template index
    INFO: Done device template BRANCH_ADVANCED
    <snip>
    INFO: Saved data-ipv6-prefix list index
    INFO: Done data-ipv6-prefix list mgmt_prefixes_ipv6
    INFO: Task completed successfully

### Restoring from backup:

    % sdwan --verbose restore all        
    INFO: Starting restore: Local workdir: "backup_10.85.136.253_20200617" -> vManage URL: "https://10.85.136.253:8443"
    INFO: Loading existing items from target vManage
    INFO: Identifying items to be pushed
    INFO: Inspecting template_device items
    INFO: Inspecting template_feature items
    INFO: Inspecting policy_vsmart items
    INFO: Inspecting policy_vedge items
    INFO: Inspecting policy_security items
    INFO: Inspecting policy_voice items
    INFO: Inspecting policy_customapp items
    INFO: Inspecting policy_definition items
    INFO: Inspecting policy_profile items
    INFO: Inspecting policy_list items
    INFO: Pushing items to vManage
    INFO: Done: Create data-ipv6-prefix list mgmt_prefixes_ipv6
    INFO: Done: Create SLA-class list Realtime_Full_Mesh
    INFO: Done: Create SLA-class list Best_Effort
    INFO: Done: Create data-prefix list mgmt_prefixes
    <snip>
    INFO: Done: Create device template BRANCH_ADVANCED
    INFO: Done: Create device template BRANCH_BASIC
    INFO: Task completed successfully
    
#### Restoring from a backup in a different directory than the default:

    % sdwan --verbose restore all --workdir my_custom_directory
    INFO: Starting restore: Local workdir: "my_custom_directory" -> vManage URL: "https://10.85.136.253:8443"
    INFO: Loading existing items from target vManage
    INFO: Identifying items to be pushed
    INFO: Inspecting template_device items
    INFO: Inspecting template_feature items
    <snip>
    INFO: Task completed successfully

#### Restoring with template attachments and policy activation:
    
    % sdwan --verbose restore all --attach
    INFO: Starting restore: Local workdir: "backup_10.85.136.253_20200617" -> vManage URL: "https://10.85.136.253:8443"
    INFO: Loading existing items from target vManage
    <snip>
    INFO: Attaching WAN Edge templates
    INFO: Waiting...
    INFO: Waiting...
    INFO: Waiting...
    INFO: Waiting...
    INFO: Completed DC_BASIC,BRANCH_BASIC
    INFO: Completed attaching WAN Edge templates
    INFO: Attaching vSmart template
    INFO: Waiting...
    INFO: Waiting...
    INFO: Completed VSMART_v1
    INFO: Completed attaching vSmart template
    INFO: Activating vSmart policy
    INFO: Waiting...
    INFO: Waiting...
    INFO: Completed Central_policy_v1
    INFO: Completed activating vSmart policy
    INFO: Task completed successfully

#### Overwriting items with the --force option:
- By default, when an item from backup has the same name as an existing item in vManage, it will be skipped by restore. Leaving the existing one intact.
- When an item, say a device template, is modified in vManage. Performing a restore from a backup taken before the modification will skip that item.
- With the --force option, items with the same name are updated with the info found in the backup.
- Sastre only updates the item when its contents differ from what is in vManage.
- If the item is associated with attached templates or activated policies, all necessary re-attach/re-activate actions are automatically performed.
- Currently, the --force option does not apply to changes in template values. 

Example:

    % sdwan --verbose restore all --workdir state_b --force
    INFO: Starting restore: Local workdir: "state_b" -> vManage URL: "https://10.85.136.253:8443"
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

### Deleting vManage items:

Dry-run, just list without deleting items matching the specified tag and regular expression:

    % sdwan --verbose delete all --regex "^DC"  --dryrun
    INFO: Starting delete, DRY-RUN mode: vManage URL: "https://10.85.136.253:8443"
    INFO: Inspecting template_device items
    INFO: DRY-RUN: Delete device template DC_BASIC
    INFO: DRY-RUN: Delete device template DC_ADVANCED
    INFO: Inspecting template_feature items
    INFO: Inspecting policy_vsmart items
    INFO: Inspecting policy_vedge items
    INFO: Inspecting policy_security items
    INFO: Inspecting policy_definition items
    INFO: Inspecting policy_list items
    INFO: Task completed successfully

Deleting items:

    % sdwan --verbose delete all --regex "^DC"
    INFO: Starting delete: vManage URL: "https://10.85.136.253:8443"
    INFO: Inspecting template_device items
    INFO: Done: Delete device template DC_BASIC
    INFO: Done: Delete device template DC_ADVANCED
    INFO: Inspecting template_feature items
    INFO: Inspecting policy_vsmart items
    INFO: Inspecting policy_vedge items
    INFO: Inspecting policy_security items
    INFO: Inspecting policy_definition items
    INFO: Inspecting policy_list items
    INFO: Task completed successfully

#### Deleting with detach:
When vSmart policies are activated and device templates are attached the associated items cannot be deleted. 
The --detach option performs the necessary template detach and vSmart policy deactivate before proceeding with the delete.

    % sdwan --verbose delete all --detach
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

### Listing items from vManage or from a backup:

The list task can be used to list items from a target vManage, or a backup directory, matching a criteria of item tag(s) and regular expression.

List device templates and feature templates from target vManage:

    % sdwan --verbose list configuration template_device template_feature
    INFO: Starting list configuration: vManage URL: "https://198.18.1.10:8443"
    INFO: List criteria matched 45 items
    +---------------------------+--------------------------------------+------------------+------------------+
    | Name                      | ID                                   | Tag              | Type             |
    +---------------------------+--------------------------------------+------------------+------------------+
    | BRANCH_ADVANCED           | 6ece1f27-fbfa-4730-9a8f-b61bfd380047 | template_device  | device template  |
    | VSMART_v1                 | ba623cf6-5d2c-4676-a763-11b9cf866074 | template_device  | device template  |
    | BRANCH_BASIC              | 5e362c85-8251-428a-b650-d364f8e15a22 | template_device  | device template  |
    <snip>
    | vSmart_VPN0_Interface_v1  | be09349e-308e-4ca5-a306-fb7bcd5bcb28 | template_feature | feature template |
    +---------------------------+--------------------------------------+------------------+------------------+
    INFO: Task completed successfully
 
List all items from target vManage with name starting with 'DC':
 
    % sdwan --verbose list configuration all --regex "^DC"
    INFO: Starting list configuration: vManage URL: "https://198.18.1.10:8443"
    INFO: List criteria matched 2 items
    +-------------+--------------------------------------+-----------------+-----------------+
    | Name        | ID                                   | Tag             | Type            |
    +-------------+--------------------------------------+-----------------+-----------------+
    | DC_BASIC    | 2ba8c66a-eadd-4a63-97c9-50d58a43b6b5 | template_device | device template |
    | DC_ADVANCED | b042ed29-3875-4118-b800-a0b00542b58e | template_device | device template |
    +-------------+--------------------------------------+-----------------+-----------------+
    INFO: Task completed successfully

List all items from backup directory with name starting with 'DC':

    % sdwan --verbose list configuration all --regex "^DC" --workdir backup_10.85.136.253_20191206
    INFO: Starting list configuration: Local workdir: "backup_10.85.136.253_20191206"
    INFO: List criteria matched 2 items
    +-------------+--------------------------------------+-----------------+-----------------+
    | Name        | ID                                   | Tag             | Type            |
    +-------------+--------------------------------------+-----------------+-----------------+
    | DC_ADVANCED | bf322748-8dfd-4cb0-a9e4-5d758be239a0 | template_device | device template |
    | DC_BASIC    | 09c02518-9557-4ae2-9031-7e6b3e7323fc | template_device | device template |
    +-------------+--------------------------------------+-----------------+-----------------+
    INFO: Task completed successfully
    
List also allows displaying device certificate information.

    % sdwan --verbose list certificate                     
    INFO: Starting list certificates: vManage URL: "https://198.18.1.10:8443"
    INFO: List criteria matched 5 items
    +------------+------------------------------------------+----------------------------------+----------------------------+--------+
    | Hostname   | Chassis                                  | Serial                           | State                      | Status |
    +------------+------------------------------------------+----------------------------------+----------------------------+--------+
    | DC1-VEDGE1 | ebdc8bd9-17e5-4eb3-a5e0-f438403a83de     | ee08f743                         | certificate installed      | valid  |
    | -          | 52c7911f-c5b0-45df-b826-3155809a2a1a     | 24801375888299141d620fbdb02de2d4 | bootstrap config generated | valid  |
    | DC1-VEDGE2 | f21dbb35-30b3-47f4-93bb-d2b2fe092d35     | b02445f6                         | certificate installed      | valid  |
    | BR1-CEDGE2 | CSR-04ed104b-86bb-4cb3-bd2b-a0d0991f6872 | AAC6C8F0                         | certificate installed      | valid  |
    | BR1-CEDGE1 | CSR-940ad679-a16a-48ea-9920-16278597d98e | 487D703A                         | certificate installed      | valid  |
    +------------+------------------------------------------+----------------------------------+----------------------------+--------+
    INFO: Task completed successfully


Similar to the list task, show tasks can be used to show items from a target vManage, or a backup. With show tasks, additional details about the selected items are displayed. The item id, name or a regular expression can be used to identify which item(s) to display.

    % sdwan show-template values --name DC_BASIC
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

### Modifying device certificate validity status:

Restore certificate validity status from a backup:

    % sdwan --verbose certificate restore --workdir test
    INFO: Starting certificate: Restore status workdir: "test" > vManage URL: "https://198.18.1.10:8443"
    INFO: Loading WAN edge certificate list from target vManage
    INFO: Identifying items to be pushed
    INFO: Will update DC1-VEDGE1 status: valid -> staging
    INFO: Will update 52c7911f-c5b0-45df-b826-3155809a2a1a status: valid -> invalid
    INFO: Will update DC1-VEDGE2 status: valid -> staging
    INFO: Will update BR1-CEDGE2 status: valid -> staging
    INFO: Will update BR1-CEDGE1 status: valid -> staging
    INFO: Pushing certificate status changes to vManage
    INFO: Certificate sync with controllers
    INFO: Waiting...
    INFO: Completed certificate sync with controllers
    INFO: Task completed successfully

Set certificate validity status to a desired value:

    % sdwan --verbose certificate set valid             
    INFO: Starting certificate: Set status to "valid" > vManage URL: "https://198.18.1.10:8443"
    INFO: Loading WAN edge certificate list from target vManage
    INFO: Identifying items to be pushed
    INFO: Will update DC1-VEDGE1 status: staging -> valid
    INFO: Will update 52c7911f-c5b0-45df-b826-3155809a2a1a status: invalid -> valid
    INFO: Will update DC1-VEDGE2 status: staging -> valid
    INFO: Will update BR1-CEDGE2 status: staging -> valid
    INFO: Will update BR1-CEDGE1 status: staging -> valid
    INFO: Pushing certificate status changes to vManage
    INFO: Certificate sync with controllers
    INFO: Waiting...
    INFO: Completed certificate sync with controllers
    INFO: Task completed successfully

### Migrating templates to 20.1
- Template migration from 18.4, 19.2 or 19.3 to 20.1 is supported. Maintenance numbers are not relevant to the migration. That is, 20.1 and 20.1.1 can be specified without any difference in terms of template migration.
- The source of templates can be a live vManage or a backup. The destination is always a local directory. A restore task is then used to push migrated items to the target vManage.
- Device attachments and template values are currently not handled by the migrate task. For instance, devices attached to a device template are left on that same template even when a new migrated template is created. 

Migrating off a live vManage:

    % sdwan --verbose migrate all dcloud_migrated    
    INFO: Starting migrate: vManage URL: "https://198.18.1.10:8443" 18.4 -> 20.1 Local output dir: "dcloud_migrated"
    INFO: Loaded template migration recipes
    INFO: Inspecting policy_list items
    INFO: Saved VPN list index
    INFO: Saved VPN list myvpns
    INFO: Saved VPN list corpVPN
    INFO: Saved VPN list pciVPN
    INFO: Saved VPN list guestVPN
    INFO: Saved VPN list ALLVPNs
    INFO: Saved URL-whitelist list index
    INFO: Saved URL-whitelist list Cisco
    <snip>
    INFO: Inspecting template_device items
    INFO: Saved device template index
    INFO: Saved device template vSmartConfigurationTemplate
    INFO: Saved device template VSMART-device-template
    INFO: Saved device template BranchType2Template-vEdge
    INFO: Saved device template DC-vEdges
    INFO: Saved device template migrated_BranchType1Template-CSR
    INFO: Task completed successfully

Migrating from a local workdir:

    % sdwan --verbose migrate all --workdir sastre_cx_golden_repo sastre_cx_golden_repo_201
    INFO: Starting migrate: Local workdir: "sastre_cx_golden_repo" 18.4 -> 20.1 Local output dir: "sastre_cx_golden_repo_201"
    INFO: Loaded template migration recipes
    INFO: Inspecting policy_list items
    INFO: Saved VPN list index
    INFO: Saved VPN list ALL_VPNS
    INFO: Saved VPN list G_All_SLAN_VPN_List
    INFO: Saved URL-blacklist list index
    INFO: Saved URL-blacklist list G_URL_BL_Example_List
    INFO: Saved class list index
    INFO: Saved class list G_Voice_Class_D46_C5_V01
    <snip>
    INFO: Saved device template migrated_G_Branch_184_Single_cE4451-X_2xWAN_DHCP_L2_v01
    INFO: Task completed successfully
    
Basic customization of migrated template names:
- Using the --name option to specify the format for building migrated template names. Default is "migrated_{name}", where {name} is replaced with the original template name.

Example:

    % sdwan --verbose migrate all dcloud_migrated --workdir dcloud_192 --name "201_{name}"
    INFO: Starting migrate: Local workdir: "dcloud_192" 18.4 -> 20.1 Local output dir: "dcloud_migrated"
    INFO: Previous migration under "dcloud_migrated" was saved as "dcloud_migrated_1"
    INFO: Loaded template migration recipes
    INFO: Inspecting policy_list items
    INFO: Saved VPN list index
    INFO: Saved VPN list myvpns
    INFO: Saved VPN list corpVPN
    INFO: Saved VPN list pciVPN
    INFO: Saved VPN list guestVPN
    INFO: Saved VPN list ALLVPNs
    INFO: Saved URL-whitelist list index
    INFO: Saved URL-whitelist list Cisco
    <snip>
    INFO: Inspecting template_device items
    INFO: Saved device template index
    INFO: Saved device template vSmartConfigurationTemplate
    INFO: Saved device template VSMART-device-template
    INFO: Saved device template BranchType2Template-vEdge
    INFO: Saved device template DC-vEdges
    INFO: Saved device template 201_BranchType1Template-CSR
    INFO: Task completed successfully

Regex-based customization of migrated template names:
- This example shows a more complex --name option, containing multiple {name} entries with regular expressions.
- Additional details about the name regex syntax are provided in the "Migrate task template name manipulation" section.

Example:

    % sdwan --verbose migrate all sastre_cx_golden_repo_201 --workdir sastre_cx_golden_repo --name "{name (G_.+)_184_.+}{name (G_VPN.+)}_201{name G.+_184(_.+)}" 
    INFO: Starting migrate: Local workdir: "sastre_cx_golden_repo" 18.4 -> 20.1 Local output dir: "sastre_cx_golden_repo_201"
    INFO: Loaded template migration recipes
    INFO: Inspecting policy_list items
    <snip>
    INFO: Inspecting template_feature items
    INFO: Saved feature template index
    INFO: Saved feature template G_vEdge_201_Banner_Template_v01
    INFO: Saved feature template G_vEdge_184_Banner_Template_v01
    INFO: Saved feature template G_vEdge_184_SLAN_INT3_v01
    INFO: Saved feature template G_vEdge_184_VPN0_Transport5_TLOC_EXT_v01
    INFO: Saved feature template G_cEdge_201_Loopback0_Template_v01
    INFO: Saved feature template G_cEdge_184_Loopback0_Template_v01
    <snip>
    INFO: Saved device template G_Branch_201_Dual_cE4321_2xWAN_TLOC_L2_v01
    INFO: Saved device template G_Branch_201_Single_cE4451-X_2xWAN_DHCP_L2_v01
    INFO: Task completed successfully

## Notes

### Regular Expressions

It is recommended to always use double quotes when specifying a regular expression to --regex option:

    sdwan --verbose restore all --regex "VPN1"
     
This is to prevent the shell from interpreting special characters that could be part of the pattern provided.

Matching done by --regex is un-anchored. That is, unless anchor marks are provided (e.g. ^ or $), the specified pattern matches if present anywhere in the string. In other words, this is a search function.

The regular expression syntax supported is described in https://docs.python.org/3/library/re.html

### Migrate task template name manipulation

- The --name format specification can contain multiple occurrences of {name}. Each occurrence may contain a regular expression separated by a space: {name &lt;regex&gt;}. The regular expressions must contain one or more capturing groups, which define the segments of the original name to "copy". Segments matching each capturing group are concatenated and "pasted" to the {name} position.
- If name regex does not match, {name &lt;regex&gt;} is replaced with an empty string.
- A transform option under the list task allows one to verify of the effect of a name-regex (e.g. as used by the --name format specification in the migrate task).

Example:

    Consider the template name "G_Branch_184_Single_cE4451-X_2xWAN_DHCP_L2_v01". 
    In order to get the migrated name as "G_Branch_201_Single_cE4451-X_2xWAN_DHCP_L2_v01", one can use --name "{name (G_.+)_184_.+}_201_{name G.+_184_(.+)}".
    
    % sdwan list transform template_device --regex "G_Branch_184_Single_cE4451" --workdir sastre_cx_golden_repo "{name (G_.+)_184_.+}_201_{name G.+_184_(.+)}"
    +---------------------------------------------------------------+---------------------------------------------------------------+-----------------+-----------------+
    | Name                                                          | Transformed                                                   | Tag             | Type            |
    +---------------------------------------------------------------+---------------------------------------------------------------+-----------------+-----------------+
    | G_Branch_184_Single_cE4451-X_2xWAN_Static_2xSLAN_Trunk_L2_v01 | G_Branch_201_Single_cE4451-X_2xWAN_Static_2xSLAN_Trunk_L2_v01 | template_device | device template |
    | G_Branch_184_Single_cE4451-X_2xWAN_DHCP_L2_v01                | G_Branch_201_Single_cE4451-X_2xWAN_DHCP_L2_v01                | template_device | device template |
    +---------------------------------------------------------------+---------------------------------------------------------------+-----------------+-----------------+

### Logs

Sastre logs messages to the terminal and to log files (under the logs directory).

Debug-level and higher severity messages are always saved to the log files.

The --verbose flag controls the severity of messages printed to the terminal. If --verbose is not specified, only warning-level and higher messages are logged. When --verbose is specified, informational-level and higher messages are printed. 

### Restore behavior

By default, restore will skip items with the same name. If an existing item in vManage has the same name as an item in the backup this item is skipped from restore.

Any references/dependencies on that item are properly updated. For instance, if a feature template is not pushed to vManage because an item with the same name is already present, device templates being pushed will now point to the feature template which was already in vManage.

Adding the --force option to restore modifies this behavior. In this case Sastre will update existing items containing the same name as in the backup, but only if their content is different.

When an existing vManage item is modified, device templates may need to be reattached or vSmart policies may need to be re-activated. This is handled by Sastre as follows:
- Updating items associated with an active vSmart policy may require this policy to be re-activated. In this case, Sastre will request the policy reactivate automatically.
- On updates to a master template (e.g. device template) containing attached devices, Sastre will re-attach this device template using attachment values (variables) from the backup to feed the attach request.
- On Updates to a child template (e.g. feature template) associated with a master template containing attached devices, Sastre will re-attach the affected master template(s). In this case, Sastre will use the existing values in vManage to feed the attach request.

The implication is that if modified child templates (e.g. feature template) define new variables, re-attaching the master template will fail because not all variables will have values assigned. In this case, the recommended procedure is to detach the master template (i.e. change device to CLI mode in vManage), re-run “restore --force", then re-attach the device-template from vManage, where one would have a chance to supply any missing variable values.

## Installing

Sastre requires Python 3.6 or newer. This can be verified by pasting the following to a terminal window:

    % python3 -c "import sys;assert sys.version_info>(3,6)" && echo "ALL GOOD"

If 'ALL GOOD' is printed it means Python requirements are met. If not, download and install the latest 3.x version at Python.org (https://www.python.org/downloads/).

The recommended way to install Sastre is via pip. For development purposes, Sastre can be installed from the github repository. Both methods are described in this section.

### PIP install (recommended)

To install Sastre:

    % python3 -m pip install --upgrade cisco-sdwan
    
Verify that Sastre can run:

    % sdwan --version

### Github install

Install required Python packages:

    % python3 -m pip install --upgrade requests

Clone from the github repository:

    % git clone https://github.com/reismarcelo/sastre
    
Move to the clone directory:
    
    % cd sastre

Verify that Sastre can run:

    % python3 sdwan.py --version
