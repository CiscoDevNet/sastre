[![published](https://static.production.devnetcloud.com/codeexchange/assets/images/devnet-published.svg)](https://developer.cisco.com/codeexchange/github/repo/reismarcelo/sastre)

# Sastre - Cisco-SDWAN Automation Toolset

Sastre provides functions to assist with managing configuration elements and visualize information from Cisco SD-WAN deployments. 

Some use-cases include:
- Transfer configuration from one vManage to another. Lab or proof-of-concept environment to production, on-prem to cloud environments as examples.
- Backup, restore and delete configuration items. Tags and regular expressions can be used to select all or a subset of items.
- Visualize operational data across multiple devices. For instance, display status of control connections from multiple devices in a single table.

Sastre can also be used as an SDK to other applications, further information is available on [DevNet Sastre SDK](https://developer.cisco.com/docs/sdwan/#!sastre-sdk-overview).

Support enquires can be sent to sastre-support@cisco.com.

Note on vManage release support:
- Sastre 1.21 officially supports up to vManage 20.10. Newer vManage releases normally work without problems, just lacking support to the newer features added to that particular vManage release.

## Sastre and Sastre-Pro

Sastre is available in two flavors:
- Sastre: Public open-source under MIT license available on [Cisco DevNet repository](https://github.com/CiscoDevNet/sastre). Supports a limited set of tasks.
- Sastre-Pro: Cisco licensed version, supporting the full feature-set. Sastre-Pro is available for customers with a CX BCS subscription and Cisco internal at [Cisco eStore](https://cxtools.cisco.com/cxestore/#/toolDetail/46810).

Both flavors follow the same release numbering. For instance, if support for certain new vManage release is added to Sastre-Pro 1.x, Sastre 1.x will also have the same support (across its supported tasks).

The command "sdwan --version" will indicate the flavor that is installed.

Sastre:
```
% sdwan --version
Sastre Version 1.20. Catalog: 84 configuration items, 33 operational items.
```

Sastre-Pro:
```
% sdwan --version
Sastre-Pro Version 1.20. Catalog: 84 configuration items, 33 operational items.
```

Tasks only available on Sastre-Pro are labeled as such in the [Introduction](#introduction) section below.

## Introduction

Sastre can be installed via pip, as a container or cloned from the git repository. Please refer to the [Installing](#installing) section for details.

The command line is structured as a set of base parameters, the task specification followed by task-specific parameters:
```
sdwan <base parameters> <task> <task-specific parameters>
```

Base parameters define global options such as verbosity level, vManage credentials, etc.

Task indicates the operation to be performed. The following tasks are currently available: 
- Backup: Save vManage configuration items to a local backup.
- Restore: Restore configuration items from a local backup to vManage.
- Delete: Delete configuration items on vManage.
- Migrate: Migrate configuration items from a vManage release to another. Currently, only 18.4, 19.2 or 19.3 to 20.1 is supported. Minor revision numbers (e.g. 20.1.1) are not relevant for the template migration.
- Transform: Modify configuration items. Currently, copy and rename operations are supported. 
- Attach: Attach WAN Edges/vSmarts to templates. Allows further customization on top of the functionality available via "restore --attach".
- Detach: Detach WAN Edges/vSmarts from templates. Allows further customization on top of the functionality available via "delete --detach".
- Certificate (Sastre-Pro): Restore device certificate validity status from a backup or set to a desired value (i.e. valid, invalid or staging).
- List (Sastre-Pro): List configuration items or device certificate information from vManage or a local backup.
- Show-template (Sastre-Pro): Show details about device templates on vManage or from a local backup.
- Report (Sastre-Pro): Generate a customizable report file containing the output of multiple commands. Also provide option to generate a diff between reports.
- Show (Sastre-Pro): Run vManage real-time, state or statistics commands; collecting data from one or more devices. Query vManage alarms and events.

Task-specific parameters are provided after the task argument, customizing the task behavior. For instance, whether to execute a restore task in dry-run mode or the destination directory for a backup task. 

Notes:
- Either 'sdwan' or 'sastre' can be used as the main command.
- The command line described above, and in all examples that follow, assume Sastre was installed via PIP. 
- If Sastre was cloned from the git repository, then 'sdwan.py' or 'sastre.py' should be used instead. Please check the [Installing](#installing) section for more details.

### Base parameters

```
% sdwan --help
usage: sdwan [-h] [-a <vmanage-ip>] [-u <user>] [-p <password>] [--tenant <tenant>] [--pid <pid>] [--port <port>] [--timeout <timeout>] [--verbose] [--version] <task> ...

Sastre-Pro - Cisco-SDWAN Automation Toolset

positional arguments:
  <task>                task to be performed (backup, restore, delete, migrate, attach, detach, certificate, transform, list, show-template, show, report)
  <arguments>           task parameters, if any

options:
  -h, --help            show this help message and exit
  -a <vmanage-ip>, --address <vmanage-ip>
                        vManage IP address, can also be defined via VMANAGE_IP environment variable. If neither is provided user is prompted for the address.
  -u <user>, --user <user>
                        username, can also be defined via VMANAGE_USER environment variable. If neither is provided user is prompted for username.
  -p <password>, --password <password>
                        password, can also be defined via VMANAGE_PASSWORD environment variable. If neither is provided user is prompted for password.
  --tenant <tenant>     tenant name, when using provider accounts in multi-tenant deployments.
  --pid <pid>           CX project id, can also be defined via CX_PID environment variable. This is collected for AIDE reporting purposes. Use 0 if not applicable.
  --port <port>         vManage port number, can also be defined via VMANAGE_PORT environment variable (default: 443)
  --timeout <timeout>   REST API timeout (default: 300)
  --verbose             increase output verbosity
  --version             show program's version number and exit
```

vManage address (-a/--address), username (-u/--user), password (-p/--password), port (--port) and CX project ID (--pid) can also be provided via environment variables:
- VMANAGE_IP
- VMANAGE_USER
- VMANAGE_PASSWORD
- VMANAGE_PORT
- CX_PID

A good approach to reduce the number of parameters that need to be provided at execution time is to create rc text files exporting those environment variables for a particular vManage. This is demonstrated in the [Getting Started](#getting-started) section below.

For any of these arguments, vManage address, user, password and CX pid; user is prompted for a value if they are not provided via the environment variables or command line arguments.

CX project ID is only applicable to Sastre-Pro. CX_PID and --pid option are not available in Sastre (std). If CX project ID is not applicable, simply use value 0.

### Task-specific parameters

Task-specific parameters and options are defined after the task is provided. Each task has its own set of parameters.
```
% sdwan backup -h
usage: sdwan backup [-h] [--archive <filename> | --workdir <directory>] [--no-rollover] [--save-running]
                         [--regex <regex> | --not-regex <regex>]
                         <tag> [<tag> ...]

Sastre-Pro - Cisco-SDWAN Automation Toolset

Backup task:

positional arguments:
  <tag>                 one or more tags for selecting items to be backed up. Multiple tags should be separated by space. Available
                        tags: all, config_group, feature_profile, policy_customapp, policy_definition, policy_list,
                        policy_security, policy_vedge, policy_voice, policy_vsmart, template_device, template_feature. Special tag
                        "all" selects all items, including WAN edge certificates and device configurations.

options:
  -h, --help            show this help message and exit
  --archive <filename>  backup to zip archive
  --workdir <directory>
                        backup to directory (default: backup_198.18.1.10_20220915)
  --no-rollover         by default, if workdir already exists (before a new backup is saved) the old workdir is renamed using a
                        rolling naming scheme. This option disables this automatic rollover.
  --save-running        include the running config from each node to the backup. This is useful for reference or documentation
                        purposes. It is not needed by the restore task.
  --regex <regex>       regular expression matching item names to backup, within selected tags.
  --not-regex <regex>   regular expression matching item names NOT to backup, within selected tags.
```

#### Important concepts:
- vManage URL: Constructed from the provided vManage IP address and TCP port (default 443). All operations target this vManage.
- Workdir: Defines the location (in the local machine) where vManage data files are located. By default, it follows the format "backup_\<vmanage-ip\>_\<yyyymmdd\>". The --workdir parameter can be used to specify a different location.  Workdir is under a 'data' directory. This 'data' directory is relative to the directory where Sastre is run.
- Tag: vManage configuration items are grouped by tags, such as policy_apply, policy_definition, policy_list, template_device, etc. The special tag 'all' is used to refer to all configuration elements. Depending on the task, one or more tags can be specified in order to select groups of configuration elements.

#### Common behavior of "table" tasks:

A number of Sastre tasks provide output in the form of one or more tables. For instance, list, show-template and show tasks. There is a common set of options shared by all such tasks:

**Table export options:**
- --save-csv: Export as CSV file(s).
- --save-json: Export as JSON file(s).

**Table filtering options:**
- --include: Include rows matching the provided regular expression, exclude all other rows.
- --exclude: Exclude rows matching the provided regular expression.

Include/exclude regular expressions match on any cell value of the particular row. In other words, any cell value matching the regular expression will cause a row match.

Both --include and --exclude can be provided at simultaneously. In this case, exclude match is performed first then include.

## Getting Started

Create a directory to serve as root for backup files, log files and rc files:
```
% mkdir sastre
% cd sastre
```
    
When Sastre is executed, data/ and logs/ directories are created as needed to store backup files and application logs. These are created under the directory where Sastre is run.

Create a rc-example.sh file to include vManage details and source that file:
```
% cat <<EOF > rc-example.sh
export VMANAGE_IP='198.18.1.10'
export VMANAGE_USER='admin'
EOF
% source rc-example.sh
```

Note that in this example the password was not defined, the user will be prompted for a password.

Test vManage credentials by running a simple query listing configured device templates:
```
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
```

Any of those vManage parameters can be provided via command line as well:
```
% sdwan -p admin list configuration template_device
```

Perform a backup:
```
% sdwan --verbose backup all
INFO: Starting backup: vManage URL: "https://198.18.1.10" -> Local workdir: "backup_198.18.1.10_20210927"
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
```

Note that '--verbose' was specified so that progress information is displayed. Without this option, only warning-level messages and above are displayed.

The backup is saved under data/backup_10.85.136.253_20191206:
```
% ls
data		logs		rc-example.sh
% ls data
backup_198.18.1.10_20210927
```

## Additional Examples

### Customizing backup destination:

```
% sdwan --verbose backup all --workdir my_custom_directory
INFO: Starting backup: vManage URL: "https://198.18.1.10" -> Local workdir: "my_custom_directory"
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
```

### Backup saved as a zip file:

```
% sdwan --verbose backup all --archive my_backup_file.zip
INFO: Backup task: vManage URL: "https://198.18.1.10" -> Local archive file: "my_backup_file.zip"
INFO: Saved vManage server information
INFO: Saved WAN edge certificates
INFO: Saved device template index
<snip>
INFO: Saved local-domain list index
INFO: Done local-domain list DCLOUD
INFO: Created archive file "my_backup_file.zip"
INFO: Task completed successfully
```

Note that the zip archive is created by default in the same directory where Sastre is executed (and not under a 'data' directory, as is the case for workdir):

```
% ls *.zip
my_backup_file.zip
```

### Restoring from backup:

```
% sdwan --verbose restore all        
INFO: Starting restore: Local workdir: "backup_10.85.136.253_20200617" -> vManage URL: "https://10.85.136.253"
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
```
    
#### Restoring from a backup in a different directory than the default:

```
% sdwan --verbose restore all --workdir my_custom_directory
INFO: Starting restore: Local workdir: "my_custom_directory" -> vManage URL: "https://10.85.136.253"
INFO: Loading existing items from target vManage
INFO: Identifying items to be pushed
INFO: Inspecting template_device items
INFO: Inspecting template_feature items
<snip>
INFO: Task completed successfully
```

#### Restoring from a zip archive backup:

```
% sdwan --verbose restore all --archive my_backup_file.zip 
INFO: Restore task: Local archive file: "my_backup_file.zip" -> vManage URL: "https://198.18.1.10"
INFO: Loaded archive file "my_backup_file.zip"
INFO: Loading existing items from target vManage
INFO: Identifying items to be pushed
INFO: Inspecting config_group items
INFO: Inspecting feature_profile items
INFO: Inspecting template_device items
<snip>
INFO: Task completed successfully
```

#### Restoring with template attachments and policy activation:
    
```
% sdwan --verbose restore all --attach
INFO: Starting restore: Local workdir: "backup_10.85.136.253_20200617" -> vManage URL: "https://10.85.136.253"
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
```

#### Overwriting items with the --update option:
- By default, when an item from the backup has the same name as an existing item on vManage it will be skipped by restore.
- For instance, if a device template is modified on vManage, restoring from a backup taken before the modification will skip that item.
- With the --update option, items with the same name are updated with the info found in the backup.
- Sastre only update items when there are differences between the backup and vManage content.
- If the item is associated with attached templates or activated policies, all necessary re-attach/re-activate actions are automatically performed.
- Currently, the --update option does not inspect changes to template values. 

Example:
```
% sdwan --verbose restore all --workdir state_b --update
INFO: Starting restore: Local workdir: "state_b" -> vManage URL: "https://10.85.136.253"
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
```

### Deleting vManage items:

Dry-run, just list without deleting items matching the specified tag and regular expression:
```
% sdwan --verbose delete all --regex '^DC' --dryrun
INFO: Starting delete, DRY-RUN mode: vManage URL: "https://10.85.136.253"
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
```

Deleting items:
```
% sdwan --verbose delete all --regex '^DC'
INFO: Starting delete: vManage URL: "https://10.85.136.253"
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
```

#### Deleting with detach:
When vSmart policies are activated and device templates are attached the associated items cannot be deleted. 
The --detach option performs the necessary template detach and vSmart policy deactivate before proceeding with delete.

```
% sdwan --verbose delete all --detach
INFO: Starting delete: vManage URL: "https://10.85.136.253"
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
```

### Listing items from vManage or from a backup:

The list task can be used to show items from a target vManage, or a backup directory. Matching criteria can contain item tag(s) and regular expression.

List device templates and feature templates from target vManage:
```
% sdwan --verbose list configuration template_device template_feature
INFO: Starting list configuration: vManage URL: "https://198.18.1.10"
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
```
 
List all items from target vManage with name starting with 'DC':
```
% sdwan --verbose list configuration all --include '^DC'                                  
INFO: List configuration task: vManage URL: "https://198.18.1.10"
INFO: Selection matched 9 items
+============================================================================================================+
| Name                         | ID                                   | Tag              | Type              |
+============================================================================================================+
| DC-vEdges                    | 87f79b8f-c295-4ba9-8279-a7866055281b | template_device  | device template   |
| DC-VPN-0                     | c684bdcd-8397-4e93-b185-0474afc6a711 | template_feature | feature template  |
| DC-VPN10                     | 9c0011b9-b2eb-48ba-a262-bf6a64bcba4d | template_feature | feature template  |
| DC-VPN20                     | d8bcbe02-21db-4297-856d-03ec8de53b44 | template_feature | feature template  |
| DC1-VPN10-Interface-Template | 72b0a69a-6ce7-445d-871e-39fb7122115b | template_feature | feature template  |
| DC1-VPN20-Interface-Template | ea3e73e3-2b31-498d-8663-b0a1240e9a3c | template_feature | feature template  |
| DC1                          | 8aefe416-4f02-40bc-a141-57fb605efe72 | policy_list      | site list         |
| DC-TLOCS                     | cc13e69d-3f3a-4af0-ad28-70915d297acc | policy_list      | TLOC list         |
| DCLOUD                       | bb90f933-37d2-4639-812b-e2fb73bbb95e | policy_list      | local-domain list |
+------------------------------+--------------------------------------+------------------+-------------------+
INFO: Task completed successfully
```

List all items from backup directory with name starting with 'DC':
```
% sdwan --verbose list configuration all --include '^DC' --workdir backup_10.85.136.253_20191206
INFO: Starting list configuration: Local workdir: "backup_10.85.136.253_20191206"
INFO: Selection matched 2 items
+========================================================================================+
| Name        | ID                                   | Tag             | Type            |
+========================================================================================+
| DC_ADVANCED | bf322748-8dfd-4cb0-a9e4-5d758be239a0 | template_device | device template |
| DC_BASIC    | 09c02518-9557-4ae2-9031-7e6b3e7323fc | template_device | device template |
+-------------+--------------------------------------+-----------------+-----------------+
INFO: Task completed successfully
```
    
List also allows displaying device certificate information:
```
% sdwan --verbose list certificate                     
INFO: List certificate task: vManage URL: "https://198.18.1.10"
INFO: Selection matched 5 items
+================================================================================================================================+
| Hostname   | Chassis                                  | Serial                           | State                      | Status |
+================================================================================================================================+
| -          | 52c7911f-c5b0-45df-b826-3155809a2a1a     | 24801375888299141d620fbdb02de2d4 | bootstrap config generated | valid  |
| BR1-CEDGE1 | CSR-940ad679-a16a-48ea-9920-16278597d98e | 487D703A                         | certificate installed      | valid  |
| BR1-CEDGE2 | CSR-04ed104b-86bb-4cb3-bd2b-a0d0991f6872 | AAC6C8F0                         | certificate installed      | valid  |
| DC1-VEDGE1 | ebdc8bd9-17e5-4eb3-a5e0-f438403a83de     | ee08f743                         | certificate installed      | valid  |
| DC1-VEDGE2 | f21dbb35-30b3-47f4-93bb-d2b2fe092d35     | b02445f6                         | certificate installed      | valid  |
+------------+------------------------------------------+----------------------------------+----------------------------+--------+
INFO: Task completed successfully
```

Similar to the list task, show-template tasks can be used to display items from a target vManage or backup. With show-template values, additional details about the selected items are displayed. A regular expression can be used to select which device templates to inspect. If the inspected templates have devices attached their values are displayed.
```
% sdwan --verbose show-template values --templates '^DC'
INFO: Show-template values task: vManage URL: "https://198.18.1.10"
INFO: Inspecting device template DC-vEdges values
*** Template DC-vEdges, device DC1-VEDGE1 ***
+====================================================================================================================================================+
| Name                                 | Value                                | Variable                                                             |
+====================================================================================================================================================+
| Latitude(system_latitude)            | 37.33                                | //system/gps-location/latitude                                       |
| Longitude(system_longitude)          | -121.88                              | //system/gps-location/longitude                                      |
| Hostname(system_host_name)           | DC1-VEDGE1                           | //system/host-name                                                   |
| Site ID(system_site_id)              | 100                                  | //system/site-id                                                     |
| System IP(system_system_ip)          | 10.1.0.1                             | //system/system-ip                                                   |
| IPv4 Address(MPLS-Interface-IP)      | 100.64.0.2/30                        | /0/ge0/1/interface/ip/address                                        |
| IPv4 Address(InternetTLOCIP)         | 100.64.2.26/30                       | /0/ge0/2/interface/ip/address                                        |
| Address(Internet-GW)                 | 100.64.2.25                          | /0/vpn-instance/ip/route/0.0.0.0/0/next-hop/Internet-GW/address      |
| Address(MPLS-GW)                     | 100.64.0.1                           | /0/vpn-instance/ip/route/0.0.0.0/0/next-hop/MPLS-GW/address          |
| Router ID(ospf_router_id)            | 10.1.0.1                             | /10//router/ospf/router-id                                           |
| IPv4 Address(VPN10-Interface-IP)     | 10.1.10.150/24                       | /10/ge0/0/interface/ip/address                                       |
| Address(VPN10_DEF_GW_DC)             | 10.1.10.1                            | /10/vpn-instance/ip/route/0.0.0.0/0/next-hop/VPN10_DEF_GW_DC/address |
| IPv4 address(fw_svc_ip)              | 10.1.10.200                          | /10/vpn-instance/service/FW/address                                  |
| Interface Name(OSPF_VPN20_IF)        | ge0/3                                | /20//router/ospf/area/0/interface/OSPF_VPN20_IF/name                 |
| Router ID(ospf_router_id)            | 10.1.0.1                             | /20//router/ospf/router-id                                           |
| Address(VPN20_DEF_GW_DC)             | 10.1.20.1                            | /20/vpn-instance/ip/route/0.0.0.0/0/next-hop/VPN20_DEF_GW_DC/address |
| Interface Name(vpn20-interface-name) | ge0/3                                | /20/vpn20-interface-name/interface/if-name                           |
| IPv4 Address(VPN20-IP-Address)       | 10.1.20.150/24                       | /20/vpn20-interface-name/interface/ip/address                        |
| Interface Name(VPN512_INTERFACE)     | eth0                                 | /512/VPN512_INTERFACE/interface/if-name                              |
| IPv4 Address(VPN512_IP_ADDR)         | 198.18.3.100/24                      | /512/VPN512_INTERFACE/interface/ip/address                           |
| Address(VPN512_GW)                   | 198.18.3.1                           | /512/vpn-instance/ip/route/0.0.0.0/0/next-hop/VPN512_GW/address      |
| System IP                            | 10.1.0.1                             | csv-deviceIP                                                         |
| Chassis Number                       | ebdc8bd9-17e5-4eb3-a5e0-f438403a83de | csv-deviceId                                                         |
| Hostname                             | DC1-VEDGE1                           | csv-host-name                                                        |
| Status                               | complete                             | csv-status                                                           |
+--------------------------------------+--------------------------------------+----------------------------------------------------------------------+

*** Template DC-vEdges, device DC1-VEDGE2 ***
+====================================================================================================================================================+
| Name                                 | Value                                | Variable                                                             |
+====================================================================================================================================================+
| Latitude(system_latitude)            | 37.33                                | //system/gps-location/latitude                                       |
| Longitude(system_longitude)          | -121.88                              | //system/gps-location/longitude                                      |
| Hostname(system_host_name)           | DC1-VEDGE2                           | //system/host-name                                                   |
| Site ID(system_site_id)              | 100                                  | //system/site-id                                                     |
| System IP(system_system_ip)          | 10.1.0.2                             | //system/system-ip                                                   |
| IPv4 Address(MPLS-Interface-IP)      | 100.64.0.6/30                        | /0/ge0/1/interface/ip/address                                        |
| IPv4 Address(InternetTLOCIP)         | 100.64.2.30/30                       | /0/ge0/2/interface/ip/address                                        |
| Address(Internet-GW)                 | 100.64.2.29                          | /0/vpn-instance/ip/route/0.0.0.0/0/next-hop/Internet-GW/address      |
| Address(MPLS-GW)                     | 100.64.0.5                           | /0/vpn-instance/ip/route/0.0.0.0/0/next-hop/MPLS-GW/address          |
| Router ID(ospf_router_id)            | 10.1.0.2                             | /10//router/ospf/router-id                                           |
| IPv4 Address(VPN10-Interface-IP)     | 10.1.10.250/24                       | /10/ge0/0/interface/ip/address                                       |
| Address(VPN10_DEF_GW_DC)             | 10.1.10.1                            | /10/vpn-instance/ip/route/0.0.0.0/0/next-hop/VPN10_DEF_GW_DC/address |
| IPv4 address(fw_svc_ip)              | 10.1.10.200                          | /10/vpn-instance/service/FW/address                                  |
| Interface Name(OSPF_VPN20_IF)        | ge0/3                                | /20//router/ospf/area/0/interface/OSPF_VPN20_IF/name                 |
| Router ID(ospf_router_id)            | 10.1.0.2                             | /20//router/ospf/router-id                                           |
| Address(VPN20_DEF_GW_DC)             | 10.1.20.1                            | /20/vpn-instance/ip/route/0.0.0.0/0/next-hop/VPN20_DEF_GW_DC/address |
| Interface Name(vpn20-interface-name) | ge0/3                                | /20/vpn20-interface-name/interface/if-name                           |
| IPv4 Address(VPN20-IP-Address)       | 10.1.20.250/24                       | /20/vpn20-interface-name/interface/ip/address                        |
| Interface Name(VPN512_INTERFACE)     | eth0                                 | /512/VPN512_INTERFACE/interface/if-name                              |
| IPv4 Address(VPN512_IP_ADDR)         | 198.18.3.101/24                      | /512/VPN512_INTERFACE/interface/ip/address                           |
| Address(VPN512_GW)                   | 198.18.3.1                           | /512/vpn-instance/ip/route/0.0.0.0/0/next-hop/VPN512_GW/address      |
| System IP                            | 10.1.0.2                             | csv-deviceIP                                                         |
| Chassis Number                       | f21dbb35-30b3-47f4-93bb-d2b2fe092d35 | csv-deviceId                                                         |
| Hostname                             | DC1-VEDGE2                           | csv-host-name                                                        |
| Status                               | complete                             | csv-status                                                           |
+--------------------------------------+--------------------------------------+----------------------------------------------------------------------+
INFO: Task completed successfully
```

### Modifying device certificate validity status:

Restore certificate validity status from a backup:
```
% sdwan --verbose certificate restore --workdir test
INFO: Starting certificate: Restore status workdir: "test" > vManage URL: "https://198.18.1.10"
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
```

Set certificate validity status to a desired value:
```
% sdwan --verbose certificate set valid             
INFO: Starting certificate: Set status to "valid" > vManage URL: "https://198.18.1.10"
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
```

### Migrating templates from pre-20.1 to post-20.1
- Template migration from pre-20.1 to post-20.1 format is supported. Maintenance numbers are not relevant to the migration. That is, 20.1 and 20.1.1 can be specified without any difference in terms of template migration.
- The source of templates can be a live vManage or a backup. The destination is always a local directory. A restore task is then used to push migrated items to the target vManage.
- Device attachments and template values are currently not handled by the migrate task. For instance, devices attached to a device template are left on that same template even when a new migrated template is created. 

Migrating off a live vManage:
```
% sdwan --verbose migrate all dcloud_migrated    
INFO: Starting migrate: vManage URL: "https://198.18.1.10" 18.4 -> 20.1 Local output dir: "dcloud_migrated"
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
```

Migrating from a local workdir:
```
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
```
    
Basic customization of migrated template names:
- Using the --name option to specify the format for building migrated template names. Default is "migrated_{name}", where {name} is replaced with the original template name.

Example:
```
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
```

Regex-based customization of migrated template names:
- This example shows a more complex --name option, containing multiple {name} entries with regular expressions.
- Additional details about the name regex syntax are provided in the [Template name manipulation via name-regex](#template-name-manipulation-via-name-regex) section.

Example:
```
% sdwan --verbose migrate all sastre_cx_golden_repo_201 --workdir sastre_cx_golden_repo --name '{name (G_.+)_184_.+}{name (G_VPN.+)}_201{name G.+_184(_.+)}'
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
```

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
```
% sdwan --verbose attach edge --workdir dcloud_base --dryrun
INFO: Starting attach templates, DRY-RUN mode: Local workdir: "dcloud_base" -> vManage URL: "https://198.18.1.10"
INFO: DRY-RUN: Template attach: DC-vEdges (DC1-VEDGE1, DC1-VEDGE2), migrated_CSR_BranchType1Template-CSR (BR1-CEDGE2, BR1-CEDGE1)
INFO: Task completed successfully
```

Selecting devices to include in the attach task:
```
% sdwan --verbose attach edge --workdir dcloud_base --templates 'DC' --devices 'VEDGE2'       
INFO: Starting attach templates: Local workdir: "dcloud_base" -> vManage URL: "https://198.18.1.10"
INFO: Template attach: DC-vEdges (DC1-VEDGE2)
INFO: Attaching WAN Edges
INFO: Waiting...
INFO: Waiting...
INFO: Waiting...
INFO: Completed DC-vEdges
INFO: Completed attaching WAN Edges
INFO: Task completed successfully
```

### Verifying device operational data

The show task provides commands to display operational data from devices, and vManage alarms and events.

Show devices, realtime, state and statistics share the same set of options to filter devices to display:
  - --regex <regex> - Regular expression matching device name, type or model to display
  - --not-regex <regex> - Regular expression matching device name, type or model NOT to display.
  - --reachable - Display only reachable devices
  - --site <id> - Filter by site ID
  - --system-ip <ipv4> - Filter by system IP

Verifying inventory of devices that are reachable and name starting with "pEdge3" or "pEdge4":
```
% sdwan show devices --reachable --regex 'pEdge[3-4]'
+==================================================================================+
| Name             | System IP   | Site ID | Reachability | Type  | Model          |
+==================================================================================+
| pEdge3-ISR4331-1 | 100.1.140.1 | 140     | reachable    | vedge | vedge-ISR-4331 |
| pEdge4-ISR4331-2 | 100.1.140.2 | 140     | reachable    | vedge | vedge-ISR-4331 |
+------------------+-------------+---------+--------------+-------+----------------+
```

Listing the advertised routes from those two devices:
```
% sdwan show realtime omp adv-routes --reachable --regex 'pEdge[3-4]'
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
```

Checking control connections and local-properties:
```
% sdwan show state control --reachable --regex 'pEdge[3-4]'
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
```

Verifying app-route data:
```
% sdwan show statistics app-route --reachable --regex 'pEdge[3-4]'
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
```

Verifying app-route data from 4 days ago:
```
% sdwan --verbose show statistics app-route --days 4 --reachable --regex 'pEdge[3-4]' 
INFO: Starting show statistics: vManage URL: "https://10.122.41.140"
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
```

Checking vManage alarms:
```
% sdwan --verbose show alarms --days 1
INFO: Show alarms task: vManage URL: "https://198.18.1.10"
INFO: Records query: 2022-02-16 18:05:20 UTC -> 2022-02-17 19:05:20 UTC
+================================================================================================================================================================+
| Date & Time             | Devices    | Severity | Type                      | Message                                                                 | Active |
+================================================================================================================================================================+
| 2022-02-17 19:02:49 UTC | BR1-CEDGE1 | Critical | utd-ips-alert             | APP-DETECT DNS request for Dynamic Internet Technology domain dfgvx.com | True   |
| 2022-02-17 19:02:34 UTC | BR1-CEDGE1 | Critical | utd-ips-alert             | APP-DETECT DNS request for Dynamic Internet Technology domain dfgvx.com | True   |
| 2022-02-17 19:02:19 UTC | BR1-CEDGE1 | Critical | utd-ips-alert             | APP-DETECT DNS request for Dynamic Internet Technology domain dfgvx.com | True   |
| 2022-02-17 19:00:33 UTC | BR1-CEDGE1 | Critical | utd-file-reputation-alert | UTD file reputation alert                                               | True   |
| 2022-02-17 19:00:07 UTC | vManage    | Minor    | cpu-usage                 | System CPU usage is back to normal level (below 60%)                    | False  |
| 2022-02-17 19:00:03 UTC | BR1-CEDGE1 | Critical | utd-file-reputation-alert | UTD file reputation alert                                               | True   |
| 2022-02-17 19:00:03 UTC | BR1-CEDGE1 | Critical | utd-file-reputation-alert | UTD file reputation alert                                               | True   |
| 2022-02-17 19:00:03 UTC | vManage    | Medium   | cpu-usage                 | System CPU usage is above 60%                                           | False  |
| 2022-02-17 18:50:08 UTC | vManage    | Minor    | cpu-usage                 | System CPU usage is back to normal level (below 60%)                    | False  |
| 2022-02-17 18:50:03 UTC | vManage    | Medium   | cpu-usage                 | System CPU usage is above 60%                                           | False  |
+-------------------------+------------+----------+---------------------------+-------------------------------------------------------------------------+--------+
INFO: Task completed successfully
```

### Renaming configuration items

The transform task allows copying or renaming configuration items, including templates with attachments, activated policies and their dependencies.
```
% sdwan --verbose transform -h       
usage: sdwan transform [-h] {rename,copy,recipe} ...

Sastre-Pro - Automation Tools for Cisco SD-WAN Powered by Viptela

Transform task:

optional arguments:
  -h, --help            show this help message and exit

transform options:
  {rename,copy,recipe}
    rename              rename configuration items
    copy                copy configuration items
    recipe              transform using custom recipe
```

Transform can read from a live vManage or from a backup directory (when --workdir is specified). It always save the processed items to the provided output directory. Then restore/attach tasks can be used to push those changes to vManage.

Naming the new or renamed items can be done in a couple of ways:
- Name template: A name_regex expression defines how to build the new name based on the old name. This method is available via CLI or custom recipe.
- Name map: A 1-1 mapping from old name to new name is defined. This method is only available when using custom recipes.
- Name map + name template: When both name map and name template are defined, name map lookup is done first. Only if no match is found on name map, name template processing is done.

Renaming a feature-template using name template via transform rename:
- Rename Logging_Template_cEdge to Logging_Template_v01
```
% sdwan list config template_feature --include '^Logging'
+=====================================================================================================+
| Name                   | ID                                   | Tag              | Type             |
+=====================================================================================================+
| Logging_Template_cEdge | 1613ce4c-d098-4a24-8192-ef77d27dd0c4 | template_feature | feature template |
+------------------------+--------------------------------------+------------------+------------------+

% sdwan --verbose transform rename template_feature --regex '^Logging' '{name (Logging_Template)_cEdge}_v01' cleaned_configs
INFO: Transform task: vManage URL: "https://198.18.1.10" -> Local output dir: "cleaned_configs"
INFO: Saved vManage server information
INFO: Inspecting policy_list items
INFO: Inspecting policy_profile items
INFO: Inspecting policy_definition items
INFO: Inspecting policy_customapp items
INFO: Inspecting policy_voice items
INFO: Inspecting policy_security items
INFO: Inspecting policy_vedge items
INFO: Inspecting policy_vsmart items
INFO: Inspecting template_feature items
INFO: Matched feature template Logging_Template_cEdge
INFO: Replacing feature template: Logging_Template_cEdge -> Logging_Template_v01
INFO: Inspecting template_device items
INFO: Task completed successfully
```

Push changes to vManage using the restore task:
- Note that --update option is used. This is so device template changes are detected and updated accordingly, with template reattach triggered as needed.
```
% sdwan --verbose restore all --update --workdir cleaned_configs                         
INFO: Restore task: Local workdir: "cleaned_configs" -> vManage URL: "https://198.18.1.10"
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
INFO: Done: Create feature template Logging_Template_v01
INFO: Updating device template BranchType1Template-cEdge requires reattach
INFO: Template attach: BranchType1Template-cEdge (BR1-CEDGE2, BR1-CEDGE1)
INFO: Reattaching templates
INFO: Waiting...
INFO: Waiting...
INFO: Waiting...
INFO: Waiting...
INFO: Completed BranchType1Template-cEdge
INFO: Completed reattaching templates
INFO: Done: Update device template BranchType1Template-cEdge
INFO: Task completed successfully
```

Renaming multiple feature-templates using name template and name map via transform recipe:
- Using a custom recipe (defined in a YAML file or provided as a JSON string), allows more flexibility for defining which items are selected and how the new items should be named.
```
% cat recipe.yaml                                                          
---
tag: template_feature

name_template:
  regex: "^All-"
  name_regex: "{name ^All-(.+)}"

name_map:
  DC1-VPN10-Interface-Template: DC-VPN10-Interface_v01
  DC1-VPN20-Interface-Template: DC-VPN20-Interface_v01
...

% sdwan --verbose transform recipe --from-file recipe.yaml test-transform
INFO: Transform task: vManage URL: "https://198.18.1.10" -> Local output dir: "test-transform"
<< snip >>
INFO: Matched feature template All-VPN0-TEMPLATE_cEdge
INFO: Replacing feature template: All-VPN0-TEMPLATE_cEdge -> VPN0-TEMPLATE_cEdge
INFO: Inspecting template_device items
INFO: Task completed successfully
```

Push changes to vManage using the restore task:
```
% sdwan --verbose restore all --workdir test-transform --update             
INFO: Restore task: Local workdir: "test-transform" -> vManage URL: "https://198.18.1.10"
<< snip >>
INFO: Task completed successfully
```


## Notes

### Regular Expressions

It is recommended to always use single quotes when specifying a regular expression to --regex option:
```
sdwan --verbose restore all --regex 'VPN1'
```
     
This is to prevent the shell from interpreting special characters that could be part of the pattern provided.

Matching done by --regex is un-anchored. That is, unless anchor marks are provided (e.g. ^ or $), the specified pattern matches if present anywhere in the string. In other words, this is a search function.

The regular expression syntax supported is described in https://docs.python.org/3/library/re.html

#### Behavior of --regex and --not-regex:
- --regex is used to select items to include (i.e. perform task operation)
- --not-regex is used to define items not to include. That is, select all items, except the ones matching --not-regex.
- When --regex match on multiple fields (e.g. item name, item ID), an item is selected if the item name OR item ID match the regular expression provided.
- With --not-regex, when it matches on multiple fields (e.g. item name, item ID), all items are selected, except the ones where item name OR item ID match the regular expression.

### Template name manipulation via name-regex
Multiple Sastre tasks utilize name-regex for name manipulation:
- Migrate task --name option accepts a name-regex.
- Transform copy/rename tasks have a `<name-regex>` mandatory parameter. 
- Transform recipe task allow `name_regex` under `name_template` section of the recipe YAML file. 
- The 'list transform' task also take a `<name-regex>` parameter. This task was designed to facilitate testing of those expressions.

A name-regex is a template for creating a new name based on segments of an original name.

The following rules apply:
- Occurrences of {name} are replaced with the original item name.
- Sections of the original item name can be captured by providing a regular expression in the format: {name &lt;regex&gt;}. This regular expression must contain one or more capturing groups, which define segments of the original name to "copy". Segments matching each capturing group are concatenated and "pasted" to the {name} position.
- If the regular expression does not match, {name &lt;regex&gt;} is replaced with an empty string.

Example:
```
Consider the template name "G_Branch_184_Single_cE4451-X_2xWAN_DHCP_L2_v01". 
In order to get the migrated name as "G_Branch_201_Single_cE4451-X_2xWAN_DHCP_L2_v01", one can use --name '{name (G_.+)_184_.+}_201_{name G.+_184_(.+)}'.

% sdwan list transform template_device --regex 'G_Branch_184_Single_cE4451' --workdir sastre_cx_golden_repo '{name (G_.+)_184_.+}_201_{name G.+_184_(.+)}'
+===================================================================================================================================================================+
| Name                                                          | Transformed                                                   | Tag             | Type            |
+===================================================================================================================================================================+
| G_Branch_184_Single_cE4451-X_2xWAN_Static_2xSLAN_Trunk_L2_v01 | G_Branch_201_Single_cE4451-X_2xWAN_Static_2xSLAN_Trunk_L2_v01 | template_device | device template |
| G_Branch_184_Single_cE4451-X_2xWAN_DHCP_L2_v01                | G_Branch_201_Single_cE4451-X_2xWAN_DHCP_L2_v01                | template_device | device template |
+---------------------------------------------------------------+---------------------------------------------------------------+-----------------+-----------------+
```

### Logs

Sastre logs messages to the terminal and to log files (under the logs/ directory).

Debug-level and higher severity messages are always saved to the log files.

The --verbose flag controls the severity of messages printed to the terminal. If --verbose is not specified, only warning-level and higher messages are logged. When --verbose is specified, informational-level and higher messages are printed. 

### Restore behavior

By default, restore will skip items with the same name. If an existing item on vManage has the same name as an item in the backup this item is skipped from restore.

Any references/dependencies on that item are properly updated. For instance, if a feature template is not pushed to vManage because an item with the same name is already present, device templates being pushed will now point to the feature template which is already on vManage.

**Restore with --update:**

Adding the --update option to restore modifies this behavior. In this case, Sastre will update existing items containing the same name as in the backup, but only if their content is different.

When an existing vManage item is modified, device templates may need to be reattached or vSmart policies may need to be re-activated. This is handled as follows:
- Updating items associated with an active vSmart policy may require this policy to be re-activated. In this case, Sastre will request the policy reactivate automatically.
- On updates to master templates (e.g. device template) containing attached devices, Sastre will re-attach the device templates.
- On Updates to child templates (e.g. feature template) associated with master templates containing attached devices, Sastre will re-attach the affected master template(s).
- In all re-attach cases, Sastre will use the existing attachment values on vManage to feed the attach request.

The implication is that if modified templates define new variables re-attach will fail, because not all variables would have values assigned. In this case, the recommended procedure is to detach the master template (e.g. using detach task), re-run "restore --update", then re-attach the device-template from vManage, where one would be able to supply any missing variable values.

**Factory default items:**

If a factory-default item in the backup is a dependency (referenced by other items) that is missing on the target vManage, it is converted to a non-default item and pushed to vManage. 

A WARNING message is displayed when this condition happens. The user may want to review the corresponding templates/policies and update them to reference newer versions or equivalent factory-defaults that may be available on vManage. 

## Installing

Sastre requires Python 3.8 or newer. This can be verified by pasting the following to a terminal window:
```
% python3 -c "import sys;assert sys.version_info>(3,8)" && echo "ALL GOOD"
```

If 'ALL GOOD' is printed it means Python requirements are met. If not, download and install the latest 3.x version at Python.org (https://www.python.org/downloads/).

The recommended way to install Sastre is via pip. For development purposes, Sastre can be installed from the GitHub repository. Both methods are described in this section.

### PIP install in a virtual environment (recommended)

Create a directory to store the virtual environment and runtime files:
```
% mkdir sastre
% cd sastre
```

Create virtual environment:
```
% python3 -m venv venv
```
    
Activate virtual environment:
```
% source venv/bin/activate
(venv) %
```
- Note that the prompt is updated with the virtual environment name (venv), indicating that the virtual environment is active.
    
Upgrade initial virtual environment packages:
```
(venv) % pip install --upgrade pip setuptools
```

Install Sastre:
```
(venv) % pip install --upgrade cisco-sdwan
```
    
Verify that Sastre can run:
```
(venv) % sdwan --version
```

Notes:
- The virtual environment is deactivated by typing 'deactivate' at the command prompt.
- Before running Sastre, make sure to activate the virtual environment back again (source venv/bin/activate).

### PIP install

With this option you will likely need to run the pip commands as sudo.

Install Sastre:
```
% python3 -m pip install --upgrade cisco-sdwan
```
    
Verify that Sastre can run:
```
% sdwan --version
```

### GitHub install

Clone from the GitHub repository:
```
% git clone https://github.com/CiscoDevNet/sastre
```

Move to the clone directory:
```
% cd sastre
```

Create virtual environment:
```
% python3 -m venv venv
```
    
Activate virtual environment:
```
% source venv/bin/activate
(venv) %
```
- Note that the prompt is updated with the virtual environment name (venv), indicating that the virtual environment is active.

Upgrade initial virtual environment packages:
```
(venv) % pip install --upgrade pip setuptools
```

Install required Python packages:
```
(venv) % pip install -r requirements.txt
```

Verify that Sastre can run:
```
(venv) % python3 sdwan.py --version
```

### Docker install

First, proceed with the [GitHub install](#GitHub-install) outlined above.

Ensure you are within the directory cloned from GitHub:
```
% cd sastre
```

Then proceed as follows to build the docker container:
```
% docker build -t sastre .
Sending build context to Docker daemon    220MB
Step 1/12 : ARG http_proxy
Step 2/12 : ARG https_proxy
Step 3/12 : ARG no_proxy
Step 4/12 : FROM python:3.9-alpine
 ---> 77a605933afb
<snip>
```

Create host directory to be mounted into the container:
```
mkdir sastre-volume
```

Start the docker container:
```
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
  --port <port>         vManage port number, can also be defined via VMANAGE_PORT environment variable (default: 443)
  --timeout <timeout>   REST API timeout (default: 300)
  --verbose             increase output verbosity
  --version             show program's version number and exit
sastre:/shared-data#

sastre:/shared-data# sdwan --version
Sastre Version 1.11. Catalog: 63 configuration items, 12 realtime items.

sastre:/shared-data#
```

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
