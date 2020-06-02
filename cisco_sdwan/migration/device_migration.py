from copy import deepcopy
from collections import Hashable
from cisco_sdwan.base.processor import Operation, Processor, ProcessorException
from . import module_dir


_operations = {}  # {<operation_key>: Operation ...}


def register(operation_key, *param_keys):
    """
    Decorator used for registering operation handlers.
    :param operation_key: Operation key as used in the recipe file
    :param param_keys: Parameter keys from recipe file to be supplied to operation handler call.
    :return: decorator
    """
    def decorator(operation_fn):
        _operations[operation_key] = Operation(operation_fn, param_keys)
        return operation_fn

    return decorator


@register('replace', 'fieldHierarchyList', 'mappings')
def op_replace(template_data, field_hierarchy_list, mappings):
    """
    Search for field_hierarchy_list elements in template_data and perform replacements according to mappings
    """
    op_trace = []

    def replace(json_obj, search_list):
        if len(search_list) == 0:
            return

        if isinstance(json_obj, dict):
            for key, value in json_obj.items():
                if key == search_list[0]:
                    if len(search_list) > 1:
                        replace(value, search_list[1:])
                    elif isinstance(value, Hashable):
                        new_val = mappings.get(value)
                        if new_val is not None:
                            op_trace.append('Template {name}, updated {path}: '
                                            '{from_val} -> {to_val}'.format(name=template_data['templateName'],
                                                                            path='/'.join(field_hierarchy_list),
                                                                            from_val=value,
                                                                            to_val=new_val))
                            json_obj[key] = new_val
                else:
                    replace(value, search_list)
            
        elif isinstance(json_obj, list):
            for elem in json_obj:
                replace(elem, search_list)

    replace(template_data, field_hierarchy_list)

    return op_trace


@register('remove', 'fieldHierarchyList', 'value')
def op_remove(template_data, field_hierarchy_list, value):
    """
    Search for field_hierarchy_list elements in template_data and remove entries matching value.
    Can only remove list entries, it does not remove dictionary entries.
    """
    op_trace = []

    def match_value(elem, field):
        if isinstance(elem, dict) and elem.get(field) == value:
            op_trace.append('Template {name}, removed {path}: {value}'.format(
                name=template_data['templateName'],
                path='/'.join(field_hierarchy_list),
                value=value))
            return True
        else:
            return False

    def remove(json_obj, search_list):
        if len(search_list) == 0:
            return

        if isinstance(json_obj, dict):
            for k, v in json_obj.items():
                if k == search_list[0]:
                    if len(search_list) > 1:
                        remove(v, search_list[1:])
                else:
                    remove(v, search_list)

        elif isinstance(json_obj, list):
            if len(search_list) == 1:
                json_obj[:] = [elem for elem in json_obj if not match_value(elem, search_list[0])]

            for elem in json_obj:
                remove(elem, search_list)

    remove(template_data, field_hierarchy_list)

    return op_trace


class DeviceProcessor(Processor):
    recipe_file = module_dir().joinpath('device_template_recipes.json')

    mandatory_keys = {
        'squashedVmanageVersions': {},
        'tovManageVersion': {},
        'listOfTasks': {
            'operation': {},
            'fieldHierarchyList': {}
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

    def eval(self, device_template, new_name):
        migrated_payload = deepcopy(device_template.data)
        trace_log = []

        for recipe in self.data:
            for task in recipe['listOfTasks']:
                op = _operations.get(task['operation'])
                if op is None:
                    trace_log.append('Operation {task_op} is not supported, skipping'.format(task_op=task['operation']))
                    continue

                param_values = (task.get(param_key) for param_key in op.param_keys)
                op_trace = op.handler_fn(migrated_payload, *param_values)
                trace_log.extend(op_trace)

            if 'templateClass' in migrated_payload:
                migrated_payload['templateClass'] = 'cedge'
            else:
                trace_log.append('No templateClass in {name}'.format(name=migrated_payload['templateName']))

            migrated_payload['templateName'] = new_name
            trace_log.append('Updated name: {name}'.format(name=migrated_payload['templateName']))

        return migrated_payload, trace_log
