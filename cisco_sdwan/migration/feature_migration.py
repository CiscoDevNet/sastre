from copy import deepcopy
from numbers import Number
from cisco_sdwan.base.processor import Operation, Processor, ProcessorException
from cisco_sdwan.base.models_vmanage import CEDGE_SET
from . import module_dir

DEVICE_TYPES_TO_FILTER = {"vedge-ISR1100-6G", "vedge-ISR1100-4G", "vedge-ISR1100-4GLTE", "vedge-cloud", "vedge-1000",
                          "vedge-2000", "vedge-5000", "vedge-100", "vedge-100-B", "vedge-100-M", "vedge-100-WM",
                          "vsmart", "vbond", "vmanage"}

_operations = {}  # {<operation_key>: Operation ...}


def register(operation_key, *param_keys):
    """
    Decorator used for registering operation handlers.
    @param operation_key: Operation key as used in the recipe file
    @param param_keys: Parameter keys from recipe file to be supplied to operation handler call.
    @return: decorator
    """

    def decorator(operation_fn):
        _operations[operation_key] = Operation(operation_fn, param_keys)
        return operation_fn

    return decorator


@register('remove', 'fieldHierarchyList')
def op_remove(template_data, field_hierarchy_list):
    """
    Removes the JSONValue for the leaf key specified in fieldHierarchyList.

    For example, assume fieldHierarchyList is ['view', 'name'], then
    operRemove will first look up the JSONValue of key 'view'. Next,
    it will look up JSONValue of key 'name' if it exists, and then deletes
    the JSONValue.
    """
    op_trace = []

    def remove(container_obj, key):
        removed_value = container_obj.pop(key, None)
        if removed_value is not None:
            op_trace.append('Template {name}, field {path}: Removed'.format(name=template_data['templateName'],
                                                                            path='/'.join(field_hierarchy_list)))
        elif container_obj.get('vipObjectType', '') == 'tree':
            for next_container_obj in container_obj.get('vipValue', []):
                remove(next_container_obj, key)

    for template_obj in leaf_iter(template_data['templateDefinition'], field_hierarchy_list[:-1]):
        remove(template_obj, field_hierarchy_list[-1])

    return op_trace


@register('range', 'fieldHierarchyList', 'rangeMin', 'rangeMax')
def op_range(template_data, field_hierarchy_list, range_min, range_max):
    """
    If range_min is not None and vipValue is below, adjust vipValue to range_min
    If range_max is not None and vipValue is greater than range_max, adjust vipValue to range_max
    """
    op_trace = []
    for template_obj in leaf_iter(template_data['templateDefinition'], field_hierarchy_list):
        vip_value = template_obj.get('vipValue')
        if isinstance(vip_value, Number):
            if range_min is not None and vip_value < range_min:
                template_obj["vipValue"] = range_min
                op_trace.append('Template {name}, field {path}: Updated vipValue to min range '
                                '({from_val} -> {to_val})'.format(name=template_data['templateName'],
                                                                  path='/'.join(field_hierarchy_list),
                                                                  from_val=vip_value, to_val=range_min))
                continue

            if range_max is not None and vip_value > range_max:
                template_obj["vipValue"] = range_max
                op_trace.append('Template {name}, field {path}: Updated vipValue to max range '
                                '({from_val} -> {to_val})'.format(name=template_data['templateName'],
                                                                  path='/'.join(field_hierarchy_list),
                                                                  from_val=vip_value, to_val=range_max))
    return op_trace


@register('default', 'fieldHierarchyList', 'default')
def op_default(template_data, field_hierarchy_list, default):
    """
    Check if vipType is 'ignore' and vipValue of the leaf field is different from the default provided. If True
    then change vipType to constant and vipValue to the default provided.
    """
    op_trace = []
    for template_obj in leaf_iter(template_data['templateDefinition'], field_hierarchy_list):
        vip_value = template_obj.get('vipValue', '')
        if template_obj.get('vipType', '') == 'ignore' and vip_value != default:
            template_obj['vipType'] = 'constant'
            template_obj['vipValue'] = default
            op_trace.append('Template {name}, field {path}: Updated vipType to constant (global) and vipValue '
                            '({from_val} -> {to_val})'.format(name=template_data['templateName'],
                                                              path='/'.join(field_hierarchy_list),
                                                              from_val=vip_value, to_val=default))
    return op_trace


def leaf_iter(template_definition, field_hierarchy_list):
    """
    Yields leaf level objects from template_definition having data path matching field_hierarchy_list
    If leaf level object does not exist, nothing is yield.
    @param template_definition: json object corresponding to the template definition
    @param field_hierarchy_list: List of keys representing the field hierarchy in template_definition
    :yield: leaf level objects from template_definition
    """
    current_obj = template_definition
    for index, key in enumerate(field_hierarchy_list):
        next_obj = current_obj.get(key)
        if next_obj is not None:
            current_obj = next_obj
            continue

        if current_obj.get('vipObjectType', '') == 'tree':
            # vipValue is a list of dicts
            for next_template_object in current_obj.get('vipValue', []):
                yield from leaf_iter(next_template_object, field_hierarchy_list[index:])

        return

    yield current_obj


class FeatureProcessor(Processor):
    recipe_file = module_dir().joinpath('feature_template_recipes.json')

    mandatory_keys = {
        'squashedVmanageVersions': {},
        'tovManageVersion': {},
        'templateTypeList': {
            'fromFeatureName': {},
            'toFeatureName': {},
            'listOfTasks': {
                'operation': {},
                'fieldHierarchyList': {}
            }
        }
    }

    def __init__(self, data, from_version, to_version):
        # Extract recipes
        matched_recipes = [
            recipe for recipe in data
            if from_version in recipe['squashedVmanageVersions'] and to_version == recipe['tovManageVersion']
        ]
        if not matched_recipes:
            raise ProcessorException('No recipe available to migrate from {from_version} to {to_version}'.format(
                from_version=from_version, to_version=to_version))

        super().__init__(matched_recipes)

    def is_in_scope(self, feature_template, **kwargs):
        if feature_template.is_readonly or feature_template.device_types.isdisjoint(CEDGE_SET):
            return False
        if not feature_template.masters_attached and not kwargs.get('migrate_all', True):
            return False

        return True

    def eval(self, feature_template, new_name, new_id):
        migrated_payload = deepcopy(feature_template.data)
        trace_log = []

        old_name = feature_template.name

        for recipe in self.data:
            matched_transforms = [
                transform for transform in recipe['templateTypeList']
                if feature_template.type == transform["fromFeatureName"]
            ]
            if not matched_transforms:
                continue
            if len(matched_transforms) > 1:
                raise ProcessorException('Multiple transforms defined for {template_type}'.format(
                    template_type=feature_template.type))

            transform = matched_transforms[0]

            for task in transform['listOfTasks']:
                op = _operations.get(task['operation'])
                if op is None:
                    trace_log.append('Operation {task_op} is not supported, skipping'.format(task_op=task['operation']))
                    continue

                param_values = (task.get(param_key) for param_key in op.param_keys)
                op_trace = op.handler_fn(migrated_payload, *param_values)
                trace_log.extend(op_trace)

            migrated_payload['templateType'] = transform['toFeatureName']

        if 'gTemplateClass' in migrated_payload:
            migrated_payload['gTemplateClass'] = 'cedge'
        else:
            trace_log.append(f'No gTemplateClass in {old_name}')

        migrated_payload['templateName'] = new_name
        migrated_payload['templateId'] = new_id
        migrated_payload['deviceType'] = list(feature_template.device_types - DEVICE_TYPES_TO_FILTER)

        # Update list of device types on original feature template
        feature_template.device_types = feature_template.device_types & DEVICE_TYPES_TO_FILTER

        return migrated_payload, trace_log

    def replace_original(self):
        return False
