"""
Enhanced EAST (Enhanced Abstract Syntax Tree) Parser for Dockerfiles

This module provides functionality to parse Dockerfile content and convert it into
an enhanced abstract syntax tree representation with improved variable interpretation.

Key Features:
- Multi-stage build support with dependency tracking
- Enhanced environment variable and argument parsing with variable component extraction
- Script detection and content extraction
- Port and protocol parsing
- User/group ID parsing
- File copy/add operations with source/destination mapping
- Variable metadata extraction and classification
"""

from anytree import Node
import json
from dockerfile_parse import DockerfileParser
import os
from pathlib import Path
import re


def variableExists(x):
    """
    Check if a string contains Docker environment variable syntax and extract variable information
    
    Handles complex variable syntax including:
    - $VAR (simple variable)
    - ${VAR} (braced variable)
    - ${VAR:-default} (default value)
    - ${VAR:+suffix} (substitute if set)
    - ${VAR:-${INNER:-fallback}} (nested variables)
    - ${VAR#prefix} (remove prefix)
    - ${VAR%suffix} (remove suffix)
    
    Args:
        x (str): String to check for variable syntax
        
    Returns:
        tuple: (variable_name, begin_pos, end_pos) or ('', 0, 0) if no variable found
    """
    # Quick check for dollar sign
    if '$' not in x:
        return '', 0, 0
    
    # Try to match simple variables first (e.g., $VAR)
    simple_pattern = r'\$[a-zA-Z_][a-zA-Z0-9_]*'
    match = re.search(simple_pattern, x)
    if match:
        begin = match.start()
        end = match.end()
        variable = x[begin:end]
        return variable, begin, end
    
    # Try to match braced variables with nested braces (e.g., ${VAR})
    if '${' in x:
        begin = x.find('${')
        # Find the matching closing brace, handling nested braces
        brace_count = 0
        end = begin
        for i in range(begin, len(x)):
            if x[i] == '{':
                brace_count += 1
            elif x[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end = i + 1
                    break
        
        if end > begin:
            variable = x[begin:end]
            return variable, begin, end
    
    return '', 0, 0


def extract_variable_components(variable):
    """
    Extract components from a Docker variable expression
    
    Args:
        variable (str): Variable expression like ${VAR:-default}
        
    Returns:
        dict: Dictionary with variable components
    """
    # Handle simple $VAR syntax
    if not variable.startswith('$'):
        return {}
    
    if not variable.startswith('${'):
        var_name = variable[1:]  # Remove $ prefix
        return {
            'name': var_name,
            'type': 'simple',
            'default': None,
            'substitute': None,
            'operation': None
        }
    
    # Handle ${VAR} syntax
    if variable.startswith('${') and variable.endswith('}'):
        content = variable[2:-1]  # Remove ${ and }
        
        # Check for default value syntax: ${VAR:-default}
        default_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*):-([^}]*)$', content)
        if default_match:
            return {
                'name': default_match.group(1),
                'type': 'default',
                'default': default_match.group(2),
                'substitute': None,
                'operation': None
            }
        
        # Check for substitute if set syntax: ${VAR:+suffix}
        substitute_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*):\+([^}]*)$', content)
        if substitute_match:
            return {
                'name': substitute_match.group(1),
                'type': 'substitute',
                'default': None,
                'substitute': substitute_match.group(2),
                'operation': None
            }
        
        # Check for prefix removal syntax: ${VAR#prefix}
        prefix_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)#([^}]*)$', content)
        if prefix_match:
            return {
                'name': prefix_match.group(1),
                'type': 'operation',
                'default': None,
                'substitute': None,
                'operation': {
                    'type': 'remove_prefix',
                    'value': prefix_match.group(2)
                }
            }
        
        # Check for suffix removal syntax: ${VAR%suffix}
        suffix_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_]*)%([^}]*)$', content)
        if suffix_match:
            return {
                'name': suffix_match.group(1),
                'type': 'operation',
                'default': None,
                'substitute': None,
                'operation': {
                    'type': 'remove_suffix',
                    'value': suffix_match.group(2)
                }
            }
        
        # Simple braced variable: ${VAR}
        return {
            'name': content,
            'type': 'simple',
            'default': None,
            'substitute': None,
            'operation': None
        }
    
    return {}


def find_all_variables(x):
    """
    Find all variable expressions in a string
    
    Args:
        x (str): String to search for variables
        
    Returns:
        list: List of tuples (variable, begin_pos, end_pos)
    """
    if '$' not in x:
        return []
    
    variables = []
    
    # Find simple variables (e.g., $VAR)
    simple_pattern = r'\$[a-zA-Z_][a-zA-Z0-9_]*'
    for match in re.finditer(simple_pattern, x):
        begin = match.start()
        end = match.end()
        variable = x[begin:end]
        variables.append((variable, begin, end))
    
    # Find braced variables with nested braces (e.g., ${VAR})
    if '${' in x:
        pos = 0
        while True:
            begin = x.find('${', pos)
            if begin == -1:
                break
            
            # Find the matching closing brace, handling nested braces
            brace_count = 0
            end = begin
            for i in range(begin, len(x)):
                if x[i] == '{':
                    brace_count += 1
                elif x[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break
            
            if end > begin:
                variable = x[begin:end]
                variables.append((variable, begin, end))
                pos = end
            else:
                pos = begin + 1
    
    return variables


def parse_value_with_variables(value):
    """
    Parse a value string and extract variable information
    
    Args:
        value (str): Value string that may contain variables
        
    Returns:
        list: Structured representation with variable metadata
    """
    variables = find_all_variables(value)
    
    if not variables:
        # No variables found, return as plain text
        return ['text', [value]]
    
    # Variables found, structure them
    result = ['value_with_variables']
    
    # Split the value by variables and create structured representation
    last_end = 0
    for variable, begin, end in variables:
        # Add text before variable
        if begin > last_end:
            text_part = value[last_end:begin]
            if text_part:
                result.append(['text', [text_part]])
        
        # Add variable with metadata
        components = extract_variable_components(variable)
        var_structure = ['variable', ['name', [components.get('name', '')]]]
        
        if components.get('type'):
            var_structure.append(['type', [components['type']]])
        
        if components.get('default'):
            var_structure.append(['default', [components['default']]])
        
        if components.get('substitute'):
            var_structure.append(['substitute', [components['substitute']]])
        
        if components.get('operation'):
            op = components['operation']
            var_structure.append(['operation', [
                ['type', [op['type']]],
                ['value', [op['value']]]
            ]])
        
        result.append(var_structure)
        last_end = end
    
    # Add remaining text after last variable
    if last_end < len(value):
        text_part = value[last_end:]
        if text_part:
            result.append(['text', [text_part]])
    
    return result


def searchPosition(x, y):
    """
    Search for a substring in a string, accounting for Docker variable syntax
    
    This function handles cases where the search string might be inside
    a Docker environment variable (e.g., $VAR or ${VAR})
    
    Args:
        x (str): String to search in
        y (str): Substring to search for
        
    Returns:
        int: Position of substring, or -1 if not found
    """
    # Find all variables in the string
    variables = find_all_variables(x)
    pos = x.find(y)
    
    if y in x:
        # Check if the found position is inside any variable
        for variable, begin, end in variables:
            if begin <= pos < end:
                # Position is inside a variable, find next occurrence
                old = pos
                pos = x[pos + len(y):].find(y)
                if pos != -1:
                    pos += old + len(y)
                    # Check if this new position is also inside a variable
                    for var, var_begin, var_end in variables:
                        if var_begin <= pos < var_end:
                            # Still inside a variable, continue searching
                            old = pos
                            pos = x[pos + len(y):].find(y)
                            if pos != -1:
                                pos += old + len(y)
                            break
                else:
                    return -1
                break
        return pos
    return -1


def parse_image_parts(y):
    """
    Parse Docker image reference into base image and digest parts
    
    Handles image references like:
    - ubuntu:latest@sha256:abc123
    - nginx:alpine AS myapp
    
    Args:
        y (str): Image reference string
        
    Returns:
        tuple: (image_part1, image_part2) where part1 is base image and part2 is digest/alias
    """
    # Split by @ to separate base image from digest
    pos_alt = searchPosition(y, '@')
    if pos_alt != -1:
        image_part1 = y[:pos_alt]  # Base image part
        image_part2 = y[pos_alt + 1:]  # Digest part
    else:
        image_part1, image_part2 = y, None
    return image_part1, image_part2


def parse_image_name_and_tag(image_part1):
    """
    Extract image name and tag from the base image part
    
    Args:
        image_part1 (str): Base image part (e.g., "ubuntu:latest AS myapp")
        
    Returns:
        tuple: (image_name, image_tag)
    """
    # Find colon separator for tag
    pos_2points = searchPosition(image_part1, ':')
    # Find AS keyword for stage alias
    pos_as = searchPosition(image_part1, ' AS ')
    if pos_as == -1:
        pos_as = searchPosition(image_part1, ' as ')
    if pos_as != -1:
        image_part1 = image_part1[:pos_as]  # Remove the AS myapp part

    # Extract name and tag
    if pos_2points != -1 and (pos_as == -1 or pos_2points < pos_as):
        image_name = image_part1[:pos_2points]
        image_tag = image_part1[pos_2points + 1:]
    else:
        image_name = image_part1
        image_tag = None

    return image_name, image_tag


def parse_digest_and_alias(image_part2):
    """
    Parse digest and alias from the second part of image reference
    
    Args:
        image_part2 (str): Digest/alias part of image reference
        
    Returns:
        tuple: (digest, alias) where either can be None
    """
    if not image_part2:
        return None, None
    
    # Check if it's a digest (contains :)
    if ':' in image_part2:
        return image_part2, None
    else:
        # It's an alias
        return None, image_part2


def parse_alias(y):
    """
    Parse stage alias from image reference
    
    Args:
        y (str): Image reference string
        
    Returns:
        str: Stage alias or None
    """
    pos_as = searchPosition(y, ' AS ')
    if pos_as == -1:
        pos_as = searchPosition(y, ' as ')
    
    if pos_as != -1:
        return y[pos_as + 4:]  # Skip ' AS ' or ' as '
    return None


def handle_from(y, x, nb_stage):
    """
    Parse FROM instruction with enhanced variable support
    
    Args:
        y (str): FROM instruction value
        x (str): Instruction name ('FROM')
        nb_stage (int): Stage number
        
    Returns:
        list: Structured representation of FROM instruction
    """
    # Parse image parts
    image_part1, image_part2 = parse_image_parts(y)
    
    # Parse image name and tag
    image_name, image_tag = parse_image_name_and_tag(image_part1)
    
    # Parse digest and alias
    digest, alias = parse_digest_and_alias(image_part2)
    
    # Parse stage alias
    stage_alias = parse_alias(y)
    
    # Build result structure
    result = [x, ['stage', [nb_stage]]]
    
    # Add image information
    if image_name:
        result.append(['image_name', [image_name]])
    
    if image_tag:
        result.append(['image_tag', [image_tag]])
    
    if digest:
        result.append(['digest', [digest]])
    
    if stage_alias:
        result.append(['alias', [stage_alias]])
    
    return result


def handle_env(y, x):
    """
    Parse ENV instruction with enhanced variable support
    
    Handles both formats:
    - ENV KEY=value
    - ENV KEY value
    
    Args:
        y (str): ENV instruction value
        x (str): Instruction name ('ENV')
        
    Returns:
        list: Structured representation of environment variables with variable metadata
    """
    key_values = []
    pairs = y.split()
    i = 0
    while i < len(pairs):
        pair = pairs[i]
        pos_equal = pair.find('=')
        if pos_equal != -1:
            # Format: KEY=value
            key = pair[:pos_equal]
            value = pair[pos_equal + 1:]
            
            # Parse value with variable support
            parsed_value = parse_value_with_variables(value)
            
            key_value_pair = ['pair', ['key', [key]], ['value', parsed_value]]
            key_values.append(key_value_pair)
        else:
            # Format: KEY value
            if i + 1 < len(pairs):
                key = pair
                value = pairs[i + 1]
                
                # Parse value with variable support
                parsed_value = parse_value_with_variables(value)
                
                key_value_pair = ['pair', ['key', [key]], ['value', parsed_value]]
                key_values.append(key_value_pair)
                i += 1
        i += 1
    return [x, key_values]


def handle_arg(y, x):
    """
    Parse ARG instruction with enhanced variable support
    
    Handles both formats:
    - ARG name=value
    - ARG name
    
    Args:
        y (str): ARG instruction value
        x (str): Instruction name ('ARG')
        
    Returns:
        list: Structured representation of build argument with variable metadata
    """
    # Check for equals sign to separate name and value
    pos_equal = searchPosition(y, '=')
    if (pos_equal != -1):
        name = y[:pos_equal]
        value = y[pos_equal + 1:]
        
        # Parse value with variable support
        parsed_value = parse_value_with_variables(value)
        
        return [x, ['name', [name]], ['value', parsed_value]]
    return [x, ['name', [y]]]


def handle_expose(y, x):
    """
    Parse EXPOSE instruction and extract port/protocol information
    
    Handles formats like:
    - EXPOSE 80
    - EXPOSE 80/tcp
    - EXPOSE 80 443
    
    Args:
        y (str): EXPOSE instruction value
        x (str): Instruction name ('EXPOSE')
        
    Returns:
        list: Structured representation of exposed ports
    """
    ports = y.split()
    portlist = ['port']
    nb = 0
    for port1 in ports:
        nb = nb + 1
        # Check for protocol separator
        pos_anti = searchPosition(port1, '/')
        if (pos_anti != -1):
            # Port with protocol (e.g., 80/tcp)
            port = port1[:pos_anti]
            protocol = port1[pos_anti + 1:]
            y = [nb, ['value', [port]], ['protocol', [protocol]]]
        else:
            # Port without protocol
            y = [nb, ['value', [port1]]]
        portlist.append(y)
    return [x, portlist]


def handle_user(y, x):
    """
    Parse USER instruction with enhanced variable support
    
    Handles formats like:
    - USER username
    - USER username:group
    - USER uid:gid
    - USER username:group:uid:gid
    
    Args:
        y (str): USER instruction value
        x (str): Instruction name ('USER')
        
    Returns:
        list: Structured representation of user specification with variable metadata
    """
    # Parse value with variable support
    parsed_value = parse_value_with_variables(y)
    
    # Check for colon separators
    parts = y.split(':')
    if len(parts) == 1:
        # Just username
        return [x, ['user', parsed_value]]
    elif len(parts) == 2:
        # username:group or uid:gid
        username, group = parts
        return [x, ['user', parse_value_with_variables(username)], ['group', parse_value_with_variables(group)]]
    elif len(parts) == 4:
        # username:group:uid:gid
        username, group, uid, gid = parts
        return [x, 
                ['user', parse_value_with_variables(username)], 
                ['group', parse_value_with_variables(group)],
                ['uid', parse_value_with_variables(uid)],
                ['gid', parse_value_with_variables(gid)]]
    else:
        # Fallback to simple user
        return [x, ['user', parsed_value]]


def is_script(filename):
    """
    Check if a file is a script based on its extension
    
    Args:
        filename (str): Filename to check
        
    Returns:
        bool: True if file is a script
    """
    script_extensions = {'.sh', '.bash', '.zsh', '.fish', '.csh', '.ksh', '.tcsh'}
    return Path(filename).suffix.lower() in script_extensions


def handle_run(y, x):
    """
    Parse RUN instruction with enhanced variable support
    
    Handles formats like:
    - RUN command
    - RUN ["command", "arg1", "arg2"]
    
    Args:
        y (str): RUN instruction value
        x (str): Instruction name ('RUN')
        
    Returns:
        list: Structured representation of RUN command with variable metadata
    """
    # Check if it's JSON array format
    if y.startswith('[') and y.endswith(']'):
        try:
            # Parse JSON array
            import json
            commands = json.loads(y)
            if isinstance(commands, list):
                # Parse each command part with variable support
                parsed_commands = []
                for cmd in commands:
                    parsed_commands.append(parse_value_with_variables(str(cmd)))
                return [x, ['command_array', parsed_commands]]
        except json.JSONDecodeError:
            pass
    
    # Shell format - parse with variable support
    parsed_command = parse_value_with_variables(y)
    return [x, ['command', parsed_command]]


def normalize_path(path):
    """
    Normalize a file path
    
    Args:
        path (str): Path to normalize
        
    Returns:
        str: Normalized path
    """
    return str(Path(path).resolve())


def handle_copy_add(y, x, stage_aliases, current_stage_number, repo_path, dockerfile_path_local):
    """
    Parse COPY/ADD instruction with enhanced variable support
    
    Handles formats like:
    - COPY source dest
    - COPY ["source", "dest"]
    - ADD source dest
    
    Args:
        y (str): COPY/ADD instruction value
        x (str): Instruction name ('COPY' or 'ADD')
        stage_aliases (dict): Mapping of stage aliases to numbers
        current_stage_number (int): Current stage number
        repo_path (str): Repository path
        dockerfile_path_local (str): Local Dockerfile path
        
    Returns:
        list: Structured representation of copy/add operation with variable metadata
    """
    # Check if it's JSON array format
    if y.startswith('[') and y.endswith(']'):
        try:
            # Parse JSON array
            import json
            parts = json.loads(y)
            if isinstance(parts, list) and len(parts) >= 2:
                source = parts[0]
                destination = parts[1]
                # Parse with variable support
                parsed_source = parse_value_with_variables(str(source))
                parsed_destination = parse_value_with_variables(str(destination))
                return [x, ['source', parsed_source], ['destination', parsed_destination]]
        except json.JSONDecodeError:
            pass
    
    # Shell format - split by whitespace
    parts = y.split()
    if len(parts) >= 2:
        source = parts[0]
        destination = parts[1]
        
        # Parse with variable support
        parsed_source = parse_value_with_variables(source)
        parsed_destination = parse_value_with_variables(destination)
        
        return [x, ['source', parsed_source], ['destination', parsed_destination]]
    
    return [x, ['error', ['Invalid COPY/ADD format']]]


def EAST(x, temp_repo_path, dockerfile_path_local):
    """
    Enhanced EAST parser that uses improved variable detection and interpretation
    
    Args:
        x (str): Dockerfile content
        temp_repo_path (str): Temporary repository path
        dockerfile_path_local (str): Local Dockerfile path
        
    Returns:
        list: Enhanced abstract syntax tree with variable metadata
    """
    # Parse using dockerfile-parse library
    parser = DockerfileParser()
    parser.content = x
    
    # Get all instructions
    instructions = parser.structure
    
    # Initialize result structure
    result = ['stage']
    stage_number = 0
    stage_aliases = {}
    
    for instruction in instructions:
        instruction_type = instruction['instruction']
        instruction_value = instruction['value']
        
        if instruction_type == 'FROM':
            stage_number += 1
            result.append(handle_from(instruction_value, instruction_type, stage_number))
            
            # Track stage aliases
            alias = parse_alias(instruction_value)
            if alias:
                stage_aliases[alias] = stage_number
                
        elif instruction_type == 'ENV':
            result.append(handle_env(instruction_value, instruction_type))
            
        elif instruction_type == 'ARG':
            result.append(handle_arg(instruction_value, instruction_type))
            
        elif instruction_type == 'EXPOSE':
            result.append(handle_expose(instruction_value, instruction_type))
            
        elif instruction_type == 'USER':
            result.append(handle_user(instruction_value, instruction_type))
            
        elif instruction_type in ['RUN', 'CMD', 'ENTRYPOINT']:
            result.append(handle_run(instruction_value, instruction_type))
            
        elif instruction_type in ['COPY', 'ADD']:
            result.append(handle_copy_add(instruction_value, instruction_type, 
                                       stage_aliases, stage_number, temp_repo_path, dockerfile_path_local))
            
        elif instruction_type == 'WORKDIR':
            # Parse workdir with variable support
            parsed_workdir = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['path', parsed_workdir]])
            
        elif instruction_type == 'VOLUME':
            # Parse volume with variable support
            parsed_volume = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['path', parsed_volume]])
            
        elif instruction_type == 'LABEL':
            # Parse label with variable support
            parsed_label = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['label', parsed_label]])
            
        elif instruction_type == 'STOPSIGNAL':
            # Parse signal with variable support
            parsed_signal = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['signal', parsed_signal]])
            
        elif instruction_type == 'SHELL':
            # Parse shell with variable support
            parsed_shell = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['shell', parsed_shell]])
            
        elif instruction_type == 'HEALTHCHECK':
            # Parse healthcheck with variable support
            parsed_healthcheck = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['healthcheck', parsed_healthcheck]])
            
        else:
            # Unknown instruction - parse with variable support
            parsed_value = parse_value_with_variables(instruction_value)
            result.append([instruction_type, ['value', parsed_value]])
    
    return result


def create_node(data):
    """
    Create a tree node from data
    
    Args:
        data: Node data
        
    Returns:
        Node: Tree node
    """
    if isinstance(data, list) and len(data) > 0:
        name = str(data[0])
        children = []
        for child in data[1:]:
            if isinstance(child, list):
                children.append(create_node(child))
        return Node(name, children=children)
    else:
        return Node(str(data))


def json_to_tree(json_list):
    """
    Convert JSON list to tree structure
    
    Args:
        json_list (list): JSON list representation
        
    Returns:
        Node: Root node of the tree
    """
    return create_node(json_list)


def get_EAST(dockerfile_content, temp_repo_path, dockerfile_path_local):
    """
    Get enhanced EAST tree from Dockerfile content
    
    Args:
        dockerfile_content (str): Dockerfile content
        temp_repo_path (str): Temporary repository path
        dockerfile_path_local (str): Local Dockerfile path
        
    Returns:
        Node: Enhanced abstract syntax tree with variable metadata
    """
    east_data = EAST(dockerfile_content, temp_repo_path, dockerfile_path_local)
    return json_to_tree(east_data) 