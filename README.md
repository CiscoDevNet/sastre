[![published](https://static.production.devnetcloud.com/codeexchange/assets/images/devnet-published.svg)](https://developer.cisco.com/codeexchange/github/repo/reismarcelo/sastre)

# Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela

Sastre provides functions to assist with managing configuration elements and visualize information from Cisco SD-WAN deployments. 

Some use-cases include:
- Transfer configuration from one vManage to another. E.g. Lab/POC to production, on-prem to cloud, etc.
- Backup, restore and delete configuration items. Tags and regular expressions can be used to select all or a subset of items.
- Visualize state across multiple devices. For instance, display status of control connections from multiple devices in a single table.

Please send your support questions to sastre-support@cisco.com.

Note on vManage release support:
- Sastre 1.15 has full support for vManage 20.4.x, and partial support for vManage 20.5.x. Please check CHANGELOG.md for details on specific 20.5 configuration elements that are supported.
- Full 20.5 and 20.6 support is planned for Sastre 1.16.
- Aside from supporting new configuration elements (associated with new features) added to the newer vManage releases, all other Sastre functionality has been validated to work with 20.6.x.

## Sastre and Sastre-Pro

Sastre is available in two flavors:
- Sastre: Public open-source under MIT license available on [Cisco DevNet repository](https://github.com/CiscoDevNet/sastre). Supports a limited set of tasks.
- Sastre-Pro: Cisco licensed version, supporting the full feature-set. Sastre-Pro is available for customers with a CX BCS subscription and Cisco internal at [Cisco eStore](https://cxtools.cisco.com/cxestore/#/toolDetail/46810).

Both flavors follow the same release numbering. For instance, if support for certain new vManage release is added to Sastre-Pro 1.9, Sastre 1.9 will also have the same support (across its supported tasks).

The command "sdwan --version" will indicate the flavor that is installed.

    % sdwan --version
    Sastre-Pro Version 1.15. Catalog: 73 configuration items, 31 operational items.

Tasks only available on Sastre-Pro are labeled as such in the [Introduction](#introduction) section below.

## Introduction

Sastre can be installed via pip, as a container or cloned from the git repository. Please refer to the [Installing](#installing) section for details.

The command line is structured as a set of base parameters, the task specification followed by task-specific parameters:

    sdwan <base parameters> <task> <task-specific parameters>

Base parameters define global options such as verbosity level, vManage credentials, etc.

Task indicates the operation to be performed. The following tasks are currently available: 
- Backup: Save vManage configuration items to a local backup.
- Restore: Restore configuration items from a local backup to vManage.
- Delete: Delete configuration items on vManage.
- Migrate: Migrate configuration items from a vManage release to another. Currently, only 18.4, 19.2 or 19.3 to 20.1 is supported. Minor revision numbers (e.g. 20.1.1) are not relevant for the template migration.
- Attach (Sastre-Pro): Attach WAN Edges/vSmarts to templates. Allows further customization on top of the functionality available via "restore --attach".
- Detach (Sastre-Pro): Detach WAN Edges/vSmarts from templates. Allows further customization on top of the functionality available via "delete --detach".
- Certificate (Sastre-Pro): Restore device certificate validity status from a backup or set to a desired value (i.e. valid, invalid or staging).
- List (Sastre-Pro): List configuration items or device certificate information from vManage or a local backup.
- Show-template (Sastre-Pro): Show details about device templates on vManage or from a local backup.
- Report (Sastre-Pro): Generate a customizable report file containing the output of multiple commands. Also provide option to generate a diff between reports.
- Show (Sastre-Pro): Run vManage real-time, state or statistics commands; collecting data from one or more devices.

Task-specific parameters are provided after the task argument, customizing the task behavior. For instance, whether to execute a restore task in dry-run mode or the destination directory for a backup task. 

Notes:
- Either 'sdwan' or 'sastre' can be used as the main command.
- The command line described above, and in all examples that follow, assume Sastre was installed via PIP. 
- If Sastre was cloned from the git repository, then 'sdwan.py' or 'sastre.py' should be used instead. Please check the installation section for more details.

### Base parameters

    % sdwan -h
    usage: sdwan [-h] [-a <vmanage-ip>] [-u <user>] [-p <password>] [--tenant <tenant>] [--pid <pid>] [--port <port>] [--timeout <timeout>] [--verbose] [--version] <task> ...
    
    Sastre-Pro - Automation Tools for Cisco SD-WAN Powered by Viptela
    
    positional arguments:
      <task>                task to be performed (backup, restore, delete, migrate, attach, detach, certificate, list, show-template, show, report)
      <arguments>           task parameters, if any
    
    optional arguments:
      -h, --help            show this help message and exit
      -a <vmanage-ip>, --address <vmanage-ip>
                            vManage IP address, can also be defined via VMANAGE_IP environment variable. If neither is provided user is prompted for the address.
      -u <user>, --user <user>
                            username, can also be defined via VMANAGE_USER environment variable. If neither is provided user is prompted for username.
      -p <password>, --password <password>
                            password, can also be defined via VMANAGE_PASSWORD environment variable. If neither is provided user is prompted for password.
      --tenant <tenant>     tenant name, when using provider accounts in multi-tenant deployments.
      --pid <pid>           CX project id, can also be defined via CX_PID environment variable. This is collected for AIDE reporting purposes only.
      --port <port>         vManage port number, can also be defined via VMANAGE_PORT environment variable (default: 8443)
      --timeout <timeout>   REST API timeout (default: 300)
      --verbose             increase output verbosity
      --version             show program's version number and exit


vManage address (-a/--address), username (-u/--user), password (-p/--password) or port (--port) can also be provided via environment variables:
- VMANAGE_IP
- VMANAGE_USER
- VMANAGE_PASSWORD
- VMANAGE_PORT

Similarly, CX project ID (--pid) can also be provided via environment variable:
- CX_PID

A good approach to reduce the number of parameters that need to be provided at execution time is to create rc text files exporting those environment variables for a particular vManage. This is demonstrated in the Getting Started section below.

For any of these arguments, vManage address, user, password and CX pid; user is prompted for a value if they are not provided via the environment variables or command line arguments.

CX project ID is only applicable to Sastre-Pro. CX_PID and --pid option are not available in Sastre (std).

### Task-specific parameters

Task-specific parameters and options are defined after the task is provided. Each task has its own set of parameters.

    % sdwan backup -h
    usage: sdwan backup [-h] [--workdir <directory>] [--no-rollover] [--save-running] [--regex <regex> | --not-regex <regex>] <tag> [<tag> ...]
    
    Sastre-Pro - Automation Tools for Cisco SD-WAN Powered by Viptela
    
    Backup task:
    
    positional arguments:
      <tag>                 one or more tags for selecting items to be backed up. Multiple tags should be separated by space. Available tags: all, policy_customapp, policy_definition, policy_list, policy_profile, policy_security, policy_vedge, policy_voice, policy_vsmart,
                            template_device, template_feature. Special tag "all" selects all items, including WAN edge certificates and device configurations.
    
    optional arguments:
      -h, --help            show this help message and exit
      --workdir <directory>
                            backup destination (default: backup_198.18.1.10_20210927)
      --no-rollover         by default, if workdir already exists (before a new backup is saved) the old workdir is renamed using a rolling naming scheme. This option disables this automatic rollover.
      --save-running        include the running config from each node to the backup. This is useful for reference or documentation purposes. It is not needed by the restore task.
      --regex <regex>       regular expression matching item names to backup, within selected tags.
      --not-regex <regex>   regular expression matching item names NOT to backup, within selected tags.

Tasks that provide table output, such as show-template, list or show; have options to export the generated tables as CSV or JSON files via --save-csv and --save-json options. 


#### Important concepts:
- vManage URL: Constructed from the provided vManage IP address and TCP port (default 8443). All operations target this vManage.
- Workdir: Defines the location (in the local machine) where vManage data files are located. By default, it follows the format "backup_\<vmanage-ip\>_\<yyyymmdd\>". The --workdir parameter can be used to specify a different location.  Workdir is under a 'data' directory. This 'data' directory is relative to the directory where Sastre is run.
- Tag: vManage configuration items are grouped by tags, such as policy_apply, policy_definition, policy_list, template_device, etc. The special tag 'all' is used to refer to all configuration elements. Depending on the task, one or more tags can be specified in order to select groups of configuration elements.

## Getting Started

Create a directory to serve as root for backup files, log files and rc files:

    % mkdir sastre
    % cd sastre
    
When Sastre is executed, data/ and logs/ directories are created as needed to store backup files and application logs. These are created under the directory where Sastre is run.

Create a rc-example.sh file to include vManage details and source that file:

    % cat <<EOF > rc-example.sh
    export VMANAGE_IP='198.18.1.10'
    export VMANAGE_USER='admin'
    EOF
    % source rc-example.sh

Note that in this example the password was not defined, the user will be prompted for a password.

Test vManage credentials by running a simple query listing configured device templates:

    % sdwan list configuration template_device
    vManage password: 
    +============================================================================================+
    | Name            | ID                                   | Tag             | Type            |
    +============================================================================================+
    | DC_ADVANCED     | bf322748-8dfd-4cb0-a9e4-5d758be239a0 | template_device | device template |
    | DC_BASIC        | 09c02518-9557-4ae2-9031-7e6b3e7323fc | template_device | device template |
    | VSMART_v1       | 15c1962f-740e-4b89-a269-69f2cbfba296 | template_device | device template |
    | BRANCH_ADVANCED | ad449106-7ed6-442f-9ba8-820612b85981 | template_device | device template |
    | BRANCH_BASIC    | cc2f7a24-4c93-49ed-8e6b-1c107797ba95 | template_device | device template |
    +-----------------+--------------------------------------+-----------------+-----------------+

Any of those vManage parameters can be provided via command line as well:

    % sdwan -p admin list configuration template_device

Perform a backup:

    % sdwan --verbose backup all
    INFO: Starting backup: vManage URL: "https://198.18.1.10:8443" -> Local workdir: "backup_198.18.1.10_20210927"
    INFO: Saved vManage server information
    INFO: Saved WAN edge certificates
    INFO: Saved device template index
    <snip>
    INFO: Saved prefix list index
    INFO: Done prefix list DefaultRoute
    INFO: Done prefix list InfrastructureRoutes
    INFO: Saved local-domain list index
    INFO: Done local-domain list DCLOUD
    INFO: Task completed successfully
    
Note that '--verbose' was specified so that progress information is displayed. Without this option, only warning-level messages and above are displayed.

The backup is saved under data/backup_10.85.136.253_20191206:

    % ls
    data		logs		rc-example.sh
    % ls data
    backup_198.18.1.10_20210927

## Additional Examples

### Customizing backup destination:

    % sdwan --verbose backup all --workdir my_custom_directory
    INFO: Starting backup: vManage URL: "https://198.18.1.10:8443" -> Local workdir: "my_custom_directory"
    INFO: Saved vManage server information
    INFO: Saved WAN edge certificates
    INFO: Saved device template index
    <snip>
    INFO: Saved prefix list index
    INFO: Done prefix list DefaultRoute
    INFO: Done prefix list InfrastructureRoutes
    INFO: Saved local-domain list index
    INFO: Done local-domain list DCLOUD
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
- Currently, the --force option does not inspect changes to template values. 

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

    % sdwan --verbose delete all --regex "^DC" --dryrun
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
The --detach option performs the necessary template detach and vSmart policy deactivate before proceeding with delete.

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

The list task can be used to show items from a target vManage, or a backup directory. Matching criteria can contain item tag(s) and regular expression.

List device templates and feature templates from target vManage:

    % sdwan --verbose list configuration template_device template_feature
    INFO: Starting list configuration: vManage URL: "https://198.18.1.10:8443"
    INFO: List criteria matched 45 items
    +========================================================================================================+
    | Name                      | ID                                   | Tag              | Type             |
    +========================================================================================================+
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
    +========================================================================================+
    | Name        | ID                                   | Tag             | Type            |
    +========================================================================================+
    | DC_BASIC    | 2ba8c66a-eadd-4a63-97c9-50d58a43b6b5 | template_device | device template |
    | DC_ADVANCED | b042ed29-3875-4118-b800-a0b00542b58e | template_device | device template |
    +-------------+--------------------------------------+-----------------+-----------------+
    INFO: Task completed successfully

List all items from backup directory with name starting with 'DC':

    % sdwan --verbose list configuration all --regex "^DC" --workdir backup_10.85.136.253_20191206
    INFO: Starting list configuration: Local workdir: "backup_10.85.136.253_20191206"
    INFO: List criteria matched 2 items
    +========================================================================================+
    | Name        | ID                                   | Tag             | Type            |
    +========================================================================================+
    | DC_ADVANCED | bf322748-8dfd-4cb0-a9e4-5d758be239a0 | template_device | device template |
    | DC_BASIC    | 09c02518-9557-4ae2-9031-7e6b3e7323fc | template_device | device template |
    +-------------+--------------------------------------+-----------------+-----------------+
    INFO: Task completed successfully
    
List also allows displaying device certificate information.

    % sdwan --verbose list certificate                     
    INFO: Starting list certificates: vManage URL: "https://198.18.1.10:8443"
    INFO: List criteria matched 5 items
    +================================================================================================================================+
    | Hostname   | Chassis                                  | Serial                           | State                      | Status |
    +================================================================================================================================+
    | DC1-VEDGE1 | ebdc8bd9-17e5-4eb3-a5e0-f438403a83de     | ee08f743                         | certificate installed      | valid  |
    | -          | 52c7911f-c5b0-45df-b826-3155809a2a1a     | 24801375888299141d620fbdb02de2d4 | bootstrap config generated | valid  |
    | DC1-VEDGE2 | f21dbb35-30b3-47f4-93bb-d2b2fe092d35     | b02445f6                         | certificate installed      | valid  |
    | BR1-CEDGE2 | CSR-04ed104b-86bb-4cb3-bd2b-a0d0991f6872 | AAC6C8F0                         | certificate installed      | valid  |
    | BR1-CEDGE1 | CSR-940ad679-a16a-48ea-9920-16278597d98e | 487D703A                         | certificate installed      | valid  |
    +------------+------------------------------------------+----------------------------------+----------------------------+--------+
    INFO: Task completed successfully


Similar to the list task, show-template tasks can be used to display items from a target vManage, or a backup. With show-template values, additional details about the selected items are displayed. A regular expression can be used to select which device templates to inspect. If the inspected templates have devices attached their values are displayed.

    % sdwan show-template values --regex DC_BASIC
    *** Template DC_BASIC, device vedge-dc1 ***
    +===============================================================================================================================================+
    | Name                              | Value                                | Variable                                                           |
    +===============================================================================================================================================+
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

    *** Template DC_BASIC, device vedge-dc2 ***
    +===============================================================================================================================================+
    | Name                              | Value                                | Variable                                                           |
    +===============================================================================================================================================+
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

### Migrating templates from pre-20.1 to post-20.1
- Template migration from pre-20.1 to post-20.1 format is supported. Maintenance numbers are not relevant to the migration. That is, 20.1 and 20.1.1 can be specified without any difference in terms of template migration.
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

### Selectively attach/detach devices to/from templates

The attach and detach tasks expose a number of knobs to select templates and devices to be included:
- Templates regular expression, selecting templates to attach. Match on template name.
- Devices regular expression, selecting devices to attach. Match on device name.
- Reachability state
- Site-ID
- System-IP

When multiple filters are defined, the result is an AND of all filters. Dry-run can be used to validate the expected outcome.

The number of devices to include per attach/detach request (to vManage) can be defined with the --batch option.

Using dry-run mode to validate what templates and devices would be included with the attach task:

    % sdwan --verbose attach edge --workdir dcloud_base --dryrun
    INFO: Starting attach templates, DRY-RUN mode: Local workdir: "dcloud_base" -> vManage URL: "https://198.18.1.10:8443"
    INFO: DRY-RUN: Template attach: DC-vEdges (DC1-VEDGE1, DC1-VEDGE2), migrated_CSR_BranchType1Template-CSR (BR1-CEDGE2, BR1-CEDGE1)
    INFO: Task completed successfully

Selecting devices to include in the attach task:

    % sdwan --verbose attach edge --workdir dcloud_base --templates "DC" --devices "VEDGE2"         
    INFO: Starting attach templates: Local workdir: "dcloud_base" -> vManage URL: "https://198.18.1.10:8443"
    INFO: Template attach: DC-vEdges (DC1-VEDGE2)
    INFO: Attaching WAN Edges
    INFO: Waiting...
    INFO: Waiting...
    INFO: Waiting...
    INFO: Completed DC-vEdges
    INFO: Completed attaching WAN Edges
    INFO: Task completed successfully

### Verifying device operational data

The show task provides commands to display operational data from devices. 

They all share the same set of options to filter devices to display:
  - --regex <regex> - Regular expression matching device name, type or model to display
  - --not-regex <regex> - Regular expression matching device name, type or model NOT to display.
  - --reachable - Display only reachable devices
  - --site <id> - Filter by site ID
  - --system-ip <ipv4> - Filter by system IP

Verifying inventory of devices that are reachable and name starting with "pEdge3" or "pEdge4":

    % sdwan show devices --reachable --regex "pEdge[3-4]"
    +==================================================================================+
    | Name             | System IP   | Site ID | Reachability | Type  | Model          |
    +==================================================================================+
    | pEdge3-ISR4331-1 | 100.1.140.1 | 140     | reachable    | vedge | vedge-ISR-4331 |
    | pEdge4-ISR4331-2 | 100.1.140.2 | 140     | reachable    | vedge | vedge-ISR-4331 |
    +------------------+-------------+---------+--------------+-------+----------------+

Listing the advertised routes from those two devices:

    % sdwan show realtime omp adv-routes --reachable --regex "pEdge[3-4]"
    *** OMP advertised routes ***
    +=====================================================================================================================================+
    | Device           | VPN ID | Prefix           | To Peer     | Tloc color   | Tloc IP     | Protocol        | Metric | OMP Preference |
    +=====================================================================================================================================+
    | pEdge3-ISR4331-1 | 1      | 10.5.113.0/24    | 100.1.9.104 | mpls         | 100.1.140.1 | OSPF-external-2 | 20     |                |
    | pEdge3-ISR4331-1 | 1      | 10.5.113.0/24    | 100.1.9.104 | biz-internet | 100.1.140.1 | OSPF-external-2 | 20     |                |
    <snip>
    | pEdge3-ISR4331-1 | 1      | 172.18.31.0/24   | 100.1.9.105 | biz-internet | 100.1.140.1 | OSPF-intra-area | 2      |                |
    +------------------+--------+------------------+-------------+--------------+-------------+-----------------+--------+----------------+
    | pEdge4-ISR4331-2 | 1      | 10.5.113.0/24    | 100.1.9.104 | mpls         | 100.1.140.2 | OSPF-external-2 | 20     |                |
    | pEdge4-ISR4331-2 | 1      | 10.5.113.0/24    | 100.1.9.104 | biz-internet | 100.1.140.2 | OSPF-external-2 | 20     |                |
    <snip>
    | pEdge4-ISR4331-2 | 1      | 172.18.31.0/24   | 100.1.9.105 | biz-internet | 100.1.140.2 | OSPF-intra-area | 2      |                |
    +------------------+--------+------------------+-------------+--------------+-------------+-----------------+--------+----------------+

Checking control connections and local-properties:

    % sdwan show state control --reachable --regex "pEdge[3-4]"
    *** Control connections ***
    +===============================================================================================+
    | Device           | Peer System IP | Site ID | Peer Type | Local Color  | Remote Color | State |
    +===============================================================================================+
    | pEdge3-ISR4331-1 | 100.1.9.105    | 9       | vsmart    | biz-internet | default      | up    |
    | pEdge3-ISR4331-1 | 100.1.9.104    | 9       | vsmart    | biz-internet | default      | up    |
    | pEdge3-ISR4331-1 | 100.1.9.104    | 9       | vsmart    | mpls         | default      | up    |
    | pEdge3-ISR4331-1 | 100.1.9.103    | 9       | vmanage   | biz-internet | default      | up    |
    | pEdge3-ISR4331-1 | 100.1.9.105    | 9       | vsmart    | mpls         | default      | up    |
    +------------------+----------------+---------+-----------+--------------+--------------+-------+
    | pEdge4-ISR4331-2 | 100.1.9.105    | 9       | vsmart    | biz-internet | default      | up    |
    | pEdge4-ISR4331-2 | 100.1.9.104    | 9       | vsmart    | biz-internet | default      | up    |
    | pEdge4-ISR4331-2 | 100.1.9.101    | 9       | vmanage   | mpls         | default      | up    |
    | pEdge4-ISR4331-2 | 100.1.9.104    | 9       | vsmart    | mpls         | default      | up    |
    | pEdge4-ISR4331-2 | 100.1.9.105    | 9       | vsmart    | mpls         | default      | up    |
    +------------------+----------------+---------+-----------+--------------+--------------+-------+
    
    *** Control local-properties ***
    +======================================================================================================+
    | Device           | System IP   | Site ID | Device Type | Organization Name | Domain ID | Port Hopped |
    +======================================================================================================+
    | pEdge3-ISR4331-1 | 100.1.140.1 | 140     | vedge       | AS_RTP_SDA_SDWAN  | 1         | TRUE        |
    +------------------+-------------+---------+-------------+-------------------+-----------+-------------+
    | pEdge4-ISR4331-2 | 100.1.140.2 | 140     | vedge       | AS_RTP_SDA_SDWAN  | 1         | TRUE        |
    +------------------+-------------+---------+-------------+-------------------+-----------+-------------+

Verifying app-route data:

    % sdwan show statistics app-route --reachable --regex "pEdge[3-4]"
    *** Application-aware route statistics ***
    +===========================================================================================================================================================================+
    | Device           | Local System Ip | Remote System Ip | Local Color  | Remote Color | Total | Loss | Latency | Jitter | Name                                              |
    +===========================================================================================================================================================================+
    | pEdge3-ISR4331-1 | 100.1.140.1     | 100.1.150.2      | mpls         | mpls         | 132   | 0    | 30      | 3      | 100.1.140.1:mpls-100.1.150.2:mpls                 |
    | pEdge3-ISR4331-1 | 100.1.140.1     | 100.1.150.1      | mpls         | mpls         | 133   | 0    | 30      | 3      | 100.1.140.1:mpls-100.1.150.1:mpls                 |
    | pEdge3-ISR4331-1 | 100.1.140.1     | 100.1.111.1      | biz-internet | biz-internet | 133   | 0    | 146     | 64     | 100.1.140.1:biz-internet-100.1.111.1:biz-internet |
    | pEdge3-ISR4331-1 | 100.1.140.1     | 100.1.150.1      | biz-internet | biz-internet | 133   | 0    | 145     | 62     | 100.1.140.1:biz-internet-100.1.150.1:biz-internet |
    | pEdge3-ISR4331-1 | 100.1.140.1     | 100.1.150.2      | biz-internet | biz-internet | 133   | 0    | 144     | 65     | 100.1.140.1:biz-internet-100.1.150.2:biz-internet |
    +------------------+-----------------+------------------+--------------+--------------+-------+------+---------+--------+---------------------------------------------------+
    | pEdge4-ISR4331-2 | 100.1.140.2     | 100.1.150.1      | biz-internet | biz-internet | 132   | 0    | 145     | 62     | 100.1.140.2:biz-internet-100.1.150.1:biz-internet |
    | pEdge4-ISR4331-2 | 100.1.140.2     | 100.1.150.2      | biz-internet | biz-internet | 132   | 0    | 146     | 70     | 100.1.140.2:biz-internet-100.1.150.2:biz-internet |
    | pEdge4-ISR4331-2 | 100.1.140.2     | 100.1.111.1      | biz-internet | biz-internet | 132   | 0    | 148     | 65     | 100.1.140.2:biz-internet-100.1.111.1:biz-internet |
    | pEdge4-ISR4331-2 | 100.1.140.2     | 100.1.150.1      | mpls         | mpls         | 132   | 0    | 30      | 3      | 100.1.140.2:mpls-100.1.150.1:mpls                 |
    | pEdge4-ISR4331-2 | 100.1.140.2     | 100.1.150.2      | mpls         | mpls         | 133   | 0    | 30      | 3      | 100.1.140.2:mpls-100.1.150.2:mpls                 |
    +------------------+-----------------+------------------+--------------+--------------+-------+------+---------+--------+---------------------------------------------------+

Verifying app-route data from 4 days ago:

    % sdwan --verbose show statistics app-route --days 4 --reachable --regex "pEdge[3-4]" 
    INFO: Starting show statistics: vManage URL: "https://10.122.41.140:443"
    INFO: Query timestamp: 2021-04-26 15:36:12 UTC
    INFO: Retrieving application-aware route statistics from 2 devices
    *** Application-aware route statistics ***
    +===========================================================================================================================================================================+
    | Device           | Local System Ip | Remote System Ip | Local Color  | Remote Color | Total | Loss | Latency | Jitter | Name                                              |
    +===========================================================================================================================================================================+
    | pEdge3-ISR4331-1 | 100.1.140.1     | 100.1.150.2      | biz-internet | biz-internet | 133   | 0    | 59      | 6      | 100.1.140.1:biz-internet-100.1.150.2:biz-internet |
    | pEdge3-ISR4331-1 | 100.1.140.1     | 100.1.111.1      | biz-internet | biz-internet | 133   | 0    | 60      | 6      | 100.1.140.1:biz-internet-100.1.111.1:biz-internet |
    | pEdge3-ISR4331-1 | 100.1.140.1     | 100.1.150.1      | biz-internet | biz-internet | 132   | 0    | 59      | 6      | 100.1.140.1:biz-internet-100.1.150.1:biz-internet |
    | pEdge3-ISR4331-1 | 100.1.140.1     | 100.1.150.1      | mpls         | mpls         | 133   | 0    | 30      | 3      | 100.1.140.1:mpls-100.1.150.1:mpls                 |
    | pEdge3-ISR4331-1 | 100.1.140.1     | 100.1.150.2      | mpls         | mpls         | 132   | 0    | 30      | 3      | 100.1.140.1:mpls-100.1.150.2:mpls                 |
    +------------------+-----------------+------------------+--------------+--------------+-------+------+---------+--------+---------------------------------------------------+
    | pEdge4-ISR4331-2 | 100.1.140.2     | 100.1.111.1      | biz-internet | biz-internet | 133   | 0    | 60      | 7      | 100.1.140.2:biz-internet-100.1.111.1:biz-internet |
    | pEdge4-ISR4331-2 | 100.1.140.2     | 100.1.150.2      | biz-internet | biz-internet | 132   | 0    | 60      | 7      | 100.1.140.2:biz-internet-100.1.150.2:biz-internet |
    | pEdge4-ISR4331-2 | 100.1.140.2     | 100.1.150.1      | biz-internet | biz-internet | 133   | 0    | 60      | 6      | 100.1.140.2:biz-internet-100.1.150.1:biz-internet |
    | pEdge4-ISR4331-2 | 100.1.140.2     | 100.1.150.1      | mpls         | mpls         | 133   | 0    | 30      | 3      | 100.1.140.2:mpls-100.1.150.1:mpls                 |
    | pEdge4-ISR4331-2 | 100.1.140.2     | 100.1.150.2      | mpls         | mpls         | 133   | 0    | 30      | 3      | 100.1.140.2:mpls-100.1.150.2:mpls                 |
    +------------------+-----------------+------------------+--------------+--------------+-------+------+---------+--------+---------------------------------------------------+
    INFO: Task completed successfully

## Notes

### Regular Expressions

It is recommended to always use double quotes when specifying a regular expression to --regex option:

    sdwan --verbose restore all --regex "VPN1"
     
This is to prevent the shell from interpreting special characters that could be part of the pattern provided.

Matching done by --regex is un-anchored. That is, unless anchor marks are provided (e.g. ^ or $), the specified pattern matches if present anywhere in the string. In other words, this is a search function.

The regular expression syntax supported is described in https://docs.python.org/3/library/re.html

#### Behavior of --regex and --not-regex:
- --regex is used to select items to include (i.e. perform task operation)
- --not-regex is used to define items not to include. That is, select all items, except the ones matching --not-regex.
- When --regex match on multiple fields (e.g. item name, item ID), an item is selected if the item name OR item ID match the regular expression provided.
- With --not-regex, when it matches on multiple fields (e.g. item name, item ID), all items are selected, except the ones where item name OR item ID match the regular expression.

### Migrate task template name manipulation

- The --name format specification can contain multiple occurrences of {name}. Each occurrence may contain a regular expression separated by a space: {name &lt;regex&gt;}. The regular expressions must contain one or more capturing groups, which define the segments of the original name to "copy". Segments matching each capturing group are concatenated and "pasted" to the {name} position.
- If name regex does not match, {name &lt;regex&gt;} is replaced with an empty string.
- A transform option under the list task allows one to verify of the effect of a name-regex (e.g. as used by the --name format specification in the migrate task).

Example:

    Consider the template name "G_Branch_184_Single_cE4451-X_2xWAN_DHCP_L2_v01". 
    In order to get the migrated name as "G_Branch_201_Single_cE4451-X_2xWAN_DHCP_L2_v01", one can use --name "{name (G_.+)_184_.+}_201_{name G.+_184_(.+)}".
    
    % sdwan list transform template_device --regex "G_Branch_184_Single_cE4451" --workdir sastre_cx_golden_repo "{name (G_.+)_184_.+}_201_{name G.+_184_(.+)}"
    +===================================================================================================================================================================+
    | Name                                                          | Transformed                                                   | Tag             | Type            |
    +===================================================================================================================================================================+
    | G_Branch_184_Single_cE4451-X_2xWAN_Static_2xSLAN_Trunk_L2_v01 | G_Branch_201_Single_cE4451-X_2xWAN_Static_2xSLAN_Trunk_L2_v01 | template_device | device template |
    | G_Branch_184_Single_cE4451-X_2xWAN_DHCP_L2_v01                | G_Branch_201_Single_cE4451-X_2xWAN_DHCP_L2_v01                | template_device | device template |
    +---------------------------------------------------------------+---------------------------------------------------------------+-----------------+-----------------+

### Logs

Sastre logs messages to the terminal and to log files (under the logs/ directory).

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

The implication is that if modified child templates (e.g. feature template) define new variables, re-attaching the master template will fail because not all variables will have values assigned. In this case, the recommended procedure is to detach the master template (i.e. change device to CLI mode in vManage), re-run "restore --force", then re-attach the device-template from vManage, where one would have a chance to supply any missing variable values.

## Installing

Sastre requires Python 3.8 or newer. This can be verified by pasting the following to a terminal window:

    % python3 -c "import sys;assert sys.version_info>(3,8)" && echo "ALL GOOD"

If 'ALL GOOD' is printed it means Python requirements are met. If not, download and install the latest 3.x version at Python.org (https://www.python.org/downloads/).

The recommended way to install Sastre is via pip. For development purposes, Sastre can be installed from the GitHub repository. Both methods are described in this section.

### PIP install in a virtual environment (recommended)

Create a directory to store the virtual environment and runtime files:

    % mkdir sastre
    % cd sastre
    
Create virtual environment:

    % python3 -m venv venv
    
Activate virtual environment:

    % source venv/bin/activate
    (venv) %
    
- Note that the prompt is updated with the virtual environment name (venv), indicating that the virtual environment is active.
    
Upgrade initial virtual environment packages:

    (venv) % pip install --upgrade pip setuptools

To install Sastre:

    (venv) % pip install --upgrade cisco-sdwan
    
Verify that Sastre can run:

    (venv) % sdwan --version

Notes:
- The virtual environment is deactivated by typing 'deactivate' at the command prompt.
- Before running Sastre, make sure to activate the virtual environment back again (source venv/bin/activate).

### GitHub install

Clone from the GitHub repository:

    % git clone https://github.com/CiscoDevNet/sastre
    
Move to the clone directory:
    
    % cd sastre

Create virtual environment:

    % python3 -m venv venv
    
Activate virtual environment:

    % source venv/bin/activate
    (venv) %
    
- Note that the prompt is updated with the virtual environment name (venv), indicating that the virtual environment is active.
    
Upgrade initial virtual environment packages:

    (venv) % pip install --upgrade pip setuptools

Install required Python packages:

    (venv) % pip install -r requirements.txt

Verify that Sastre can run:

    (venv) % python3 sdwan.py --version

### Docker install

First, proceed with the [GitHub install](#GitHub-install) outlined above.

Ensure you are within the directory cloned from GitHub:

    % cd sastre

Then proceed as follows to build the docker container:

    % docker build -t sastre .
    Sending build context to Docker daemon    220MB
    Step 1/12 : ARG http_proxy
    Step 2/12 : ARG https_proxy
    Step 3/12 : ARG no_proxy
    Step 4/12 : FROM python:3.9-alpine
     ---> 77a605933afb
    <snip>

Create host directory to be mounted into the container:

    mkdir sastre-volume

Start the docker container:

    docker run -it --rm --hostname sastre \
     --mount type=bind,source="$(pwd)"/sastre-volume,target=/shared-data \
     sastre:latest

    usage: sdwan [-h] [-a <vmanage-ip>] [-u <user>] [-p <password>] [--tenant <tenant>] [--port <port>] [--timeout <timeout>] [--verbose] [--version] <task> ...
    
    Sastre - Automation Tools for Cisco SD-WAN Powered by Viptela
    
    positional arguments:
      <task>                task to be performed (backup, restore, delete, migrate)
      <arguments>           task parameters, if any
    
    optional arguments:
      -h, --help            show this help message and exit
      -a <vmanage-ip>, --address <vmanage-ip>
                            vManage IP address, can also be defined via VMANAGE_IP environment variable. If neither is provided user is prompted for the address.
      -u <user>, --user <user>
                            username, can also be defined via VMANAGE_USER environment variable. If neither is provided user is prompted for username.
      -p <password>, --password <password>
                            password, can also be defined via VMANAGE_PASSWORD environment variable. If neither is provided user is prompted for password.
      --tenant <tenant>     tenant name, when using provider accounts in multi-tenant deployments.
      --port <port>         vManage port number, can also be defined via VMANAGE_PORT environment variable (default: 8443)
      --timeout <timeout>   REST API timeout (default: 300)
      --verbose             increase output verbosity
      --version             show program's version number and exit
    sastre:/shared-data#
    
    sastre:/shared-data# sdwan --version
    Sastre Version 1.11. Catalog: 63 configuration items, 12 realtime items.

    sastre:/shared-data#

Notes:
- When set, host proxy environment variables (http_proxy, https_proxy and no_proxy) are used during the build and execution of the container.
- The container has a /shared-data volume.
- Sastre data/ and logs/ directories are created under /shared-data.
- A sample dcloud-lab.sh is copied to /shared-data/rc if no /shared-data/rc directory is present.
- Directory structure:
    - /shared-data/data - Used as the vManage backup data repository
    - /shared-data/logs - Where the logs are saved
    - /shared-data/rc - Used to store 'rc' files defining environment variables used by Sastre: VMANAGE_IP, VMANAGE_USER, etc.
- The suggested docker run command above bind-mounts the /shared-data volume, i.e. it is mapped to a host system directory. This facilitates transferring of data to/from the container (e.g. vManage backups). The host directory is relative to the location where the docker run command is executed.
- Docker run will spin-up the container and open an interactive session to it using the ash shell. Sdwan commands (e.g. sdwan backup all, etc.) can be executed at this point. Typing 'exit' will leave the ash shell, stop and remove the container. Everything under data, rc and logs is persisted to the corresponding host system directories.
