"""
EAST (Enhanced Abstract Syntax Tree) Parser for Dockerfiles

This module provides functionality to parse Dockerfile content and convert it into
an enhanced abstract syntax tree representation. The parser handles all major
Dockerfile instructions (FROM, ENV, ARG, EXPOSE, USER, RUN, COPY, ADD, etc.)
and creates a structured tree that can be used for analysis, visualization,
and dependency tracking between build stages.

Key Features:
- Multi-stage build support with dependency tracking
- Environment variable and argument parsing
- Script detection and content extraction
- Port and protocol parsing
- User/group ID parsing
- File copy/add operations with source/destination mapping
"""

from anytree import Node
import json
from dockerfile_parse import DockerfileParser
import os
from pathlib import Path


def variableExists(x):
    """
    Check if a string contains Docker environment variable syntax ($VAR or ${VAR})
    
    Args:
        x (str): String to check for variable syntax
        
    Returns:
        tuple: (variable_name, begin_pos, end_pos) or ('', 0, 0) if no variable found
    """
    if '$' in x:
        begin = x.find('$')
        end = x[begin:].find('}')
        variable = x[begin:end + 1]
        return variable, begin, end
    return '', 0, 0


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

    Example:
    x = "FROM ubuntu:latest"
    y = "ubuntu"
    searchPosition(x, y) # returns 4

    x = "FROM ubuntu:latest"
    y = "latest"
    searchPosition(x, y) # returns 12 because latest is at position 12
    """
    variable, begin, end = variableExists(x)
    pos = x.find(y)
    if y in x:
        if variable:
            old = pos
            while (pos in range(begin, end)) and (pos >= old):
                old = pos
                pos = x[pos + len(y):].find(y)
                if (pos != -1):
                    pos += old + len(y)
            return -1 if (pos < old) else pos
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
    pos_alt = searchPosition(y, '@')
    if pos_alt != -1:
        image_part1 = y[:pos_alt]
        image_part2 = y[pos_alt + 1:]
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

    Example:
    image_part1 = "ubuntu:latest AS myapp"
    parse_image_name_and_tag(image_part1) # returns ("ubuntu", "latest")
    """
    pos_2points = searchPosition(image_part1, ':')
    pos_as = searchPosition(image_part1, ' AS ')
    if pos_as == -1:
        pos_as = searchPosition(image_part1, ' as ')
    if pos_as != -1:
        image_part1 = image_part1[:pos_as] #remove the AS myapp part

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
        tuple: (image_digest, image_alias)

    Example:
    image_part2 = "sha256:abc123 AS myapp"
    parse_digest_and_alias(image_part2) # returns ("sha256:abc123", "myapp")

    image_part2 = "myapp"
    parse_digest_and_alias(image_part2) # returns (None, "myapp")
    """
    pos_as = searchPosition(image_part2, ' AS ')
    if pos_as == -1:
        pos_as = searchPosition(image_part2, ' as ')
    if pos_as != -1:
        image_alias = image_part2[pos_as + 4:]
        image_digest = image_part2[:pos_as]
    else:
        image_alias = None
        image_digest = image_part2
    return image_digest, image_alias


def parse_alias(y):
    """
    Extract alias from image reference
    
    Args:
        y (str): Image reference string
        
    Returns:
        tuple: (alias, position) or (None, -1) if no alias found

    Example:
    y = "ubuntu:latest AS myapp"
    parse_alias(y) # returns ("myapp", 12)
    """
    if y is None:
        return None

    pos_as = searchPosition(y, ' AS ')
    if pos_as == -1:
        pos_as = searchPosition(y, ' as ')
    return (y[pos_as + 4:], pos_as) if pos_as != -1 else (None, -1)


def handle_from(y, x, nb_stage):
    """
    Parse FROM instruction and extract all components
    
    Handles complex FROM statements like:
    - FROM ubuntu:latest
    - FROM ubuntu:latest@sha256:abc123 AS myapp
    - FROM --platform=linux/amd64 ubuntu:latest
    
    Args:
        y (str): FROM instruction value
        x (str): Instruction name ('FROM')
        nb_stage (int): Current stage number
        
    Returns:
        tuple: (parsed_result, image_alias, image_name)

    Example:
    y = "FROM ubuntu:latest"
    x = "FROM"
    nb_stage = 0
    handle_from(y, x, nb_stage) # returns ([0, ['FROM', ['image_name', ['ubuntu']]]], None, None)

    y = "FROM ubuntu:latest@sha256:abc123 AS myapp"
    x = "FROM"
    nb_stage = 0
    handle_from(y, x, nb_stage) # returns ([0, ['FROM', ['image_name', ['ubuntu']], ['image_tag', ['latest']], ['image_alias', ['myapp']]]], "myapp", "ubuntu")

    y = "FROM --platform=linux/amd64 ubuntu:latest"
    x = "FROM"
    nb_stage = 0
    handle_from(y, x, nb_stage) # returns ([0, ['FROM', ['image_name', ['ubuntu']], ['image_tag', ['latest']], ['image_alias', ['myapp']]]], "myapp", "ubuntu")
    """
    image_part1, image_part2 = parse_image_parts(y)
    image_name, image_tag = parse_image_name_and_tag(image_part1)
    image_digest, image_alias = None, None

    if image_part2:
        colons = [pos for pos, char in enumerate(image_part2) if char == ':']
        if len(colons) > 1:
            image_digest = image_part2[:colons[-1]]
            image_tag = image_part2[colons[-1] + 1:]
            image_alias, pos_as = parse_alias(image_tag)
            if image_alias:
                image_tag = image_tag[:pos_as]
        else:
            image_digest, image_alias = parse_digest_and_alias(image_part2)
    else:
        image_alias, pos_as = parse_alias(image_part1)

    result = [nb_stage, [x, ['image_name', [image_name]]]]

    if image_tag:
        result[1].append(['image_tag', [image_tag]])
    if image_alias:
        result[1].append(['image_alias', [image_alias]])
    if image_digest:
        result[1].append(['image_digest', [image_digest]])

    return result, image_alias, image_name


def handle_env(y, x):
    """
    Parse ENV instruction and extract key-value pairs
    
    Handles both formats:
    - ENV KEY=value
    - ENV KEY value
    
    Args:
        y (str): ENV instruction value
        x (str): Instruction name ('ENV')
        
    Returns:
        list: Structured representation of environment variables

    Example:
    y = "ENV KEY=value"
    x = "ENV"
    handle_env(y, x) # returns [['ENV', [['pair', ['key', ['KEY']], ['value', ['value']]]]]]

    """
    key_values = []
    pairs = y.split()
    i = 0
    while i < len(pairs):
        pair = pairs[i]
        pos_equal = pair.find('=')
        if pos_equal != -1:
            # Format: KEY=value
            key_value_pair = ['pair', ['key', [pair[:pos_equal]]], ['value', [pair[pos_equal + 1:]]]]
            key_values.append(key_value_pair)
        else:
            # Format: KEY value
            if i + 1 < len(pairs):
                key_value_pair = ['pair', ['key', [pair]], ['value', [pairs[i + 1]]]]
                key_values.append(key_value_pair)
                i += 1
        i += 1
    return [x, key_values]


def handle_arg(y, x):
    """
    Parse ARG instruction
    
    Handles both formats:
    - ARG name=value
    - ARG name
    
    Args:
        y (str): ARG instruction value
        x (str): Instruction name ('ARG')
        
    Returns:
        list: Structured representation of build argument

    Example:
    y = "ARG name=value"
    x = "ARG"
    handle_arg(y, x) # returns [['ARG', [['name', ['name']], ['value', ['value']]]]]

    y = "ARG name"
    """
    pos_equal = searchPosition(y, '=')
    if (pos_equal != -1):
        name = y[:pos_equal]
        value = y[pos_equal + 1:]
        return [x, ['name', [name]], ['value', [value]]]
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

    Example:
    y = "EXPOSE 80"
    x = "EXPOSE"
    handle_expose(y, x) # returns [['EXPOSE', [['port', ['80']]]]]

    """
    ports = y.split()
    portlist = ['port']
    nb = 0
    for port1 in ports:
        nb = nb + 1
        pos_anti = searchPosition(port1, '/')
        if (pos_anti != -1):
            port = port1[:pos_anti]
            protocol = port1[pos_anti + 1:]
            y = [nb, ['value', [port]], ['protocol', [protocol]]]
        else:
            y = [nb, ['value', [port1]]]
        portlist.append(y)
    return [x, portlist]


def handle_user(y, x):
    """
    Parse USER instruction
    
    Handles formats like:
    - USER username
    - USER uid
    - USER username:group
    - USER uid:gid
    
    Args:
        y (str): USER instruction value
        x (str): Instruction name ('USER')
        
    Returns:
        list: Structured representation of user specification

    Example:
    y = "USER username"
    x = "USER"
    handle_user(y, x) # returns [['USER', [['user', ['username']]]]]

    y = "USER uid"
    x = "USER"
    handle_user(y, x) # returns [['USER', [['uid', ['uid']]]]]

    y = "USER username:group"
    x = "USER"
    handle_user(y, x) # returns [['USER', [['user', ['username']], ['group', ['group']]]]]

    """
    parts = y.split(':')
    if len(parts) == 1:
        try:
            uid = int(parts[0])
            return [x, ['uid', [uid]]]
        except ValueError:
            return [x, ['user', [parts[0]]]]
    elif len(parts) == 2:
        try:
            uid = int(parts[0])
            gid = int(parts[1])
            return [x, ['uid', [uid]], ['gid', [gid]]]
        except ValueError:
            return [x, [
                'user', [parts[0]]], ['group', [parts[1]]]]


def is_script(filename):
    """
    Check if a filename represents a script file
    
    Args:
        filename (str): Filename to check
        
    Returns:
        bool: True if filename has script extension
    """
    script_exts = ['.sh', '.bash', '.zsh', '.dash']
    return any(filename.endswith(ext) for ext in script_exts)


def handle_run(y, x):
    """
    Parse RUN instruction and handle script detection
    
    This function:
    1. Splits RUN commands by '&&' to handle multiple commands
    2. Detects if any command references a script file
    3. Extracts script content if the file exists in the repository
    4. Maps container paths to repository paths
    
    Args:
        y (str): RUN instruction value
        x (str): Instruction name ('RUN')
        
    Returns:
        list: Structured representation of RUN commands

    Example:
    y = "RUN apt-get update && apt-get install -y curl"
    x = "RUN"
    handle_run(y, x) # returns [['RUN', [['command', ['apt-get update']], ['command', ['apt-get install -y curl']]]]]

    y = "RUN curl -sL https://deb.nodesource.com/setup_14.x | bash -"
    x = "RUN"
    handle_run(y, x) # returns [['RUN', [['command', ['curl -sL https://deb.nodesource.com/setup_14.x | bash -']]]]]
    """
    cwd = '/'
    sub_commands = [cmd.strip() for cmd in y.split('&&')]
    processed_commands = []

    for sub_command in sub_commands:
        if not sub_command.startswith('/'):
            script_path_in_container = os.path.normpath(os.path.join(cwd, sub_command))
        else:
            script_path_in_container = sub_command

        script_path = None
        for container_path, repo_path in script_dict.items():
            if script_path_in_container.startswith(container_path):
                relative_path_in_container = os.path.relpath(script_path_in_container, container_path)
                script_path = os.path.join(repo_path, relative_path_in_container)
                break

        if script_path and os.path.isfile(script_path):
            try:
                with open(script_path, 'r') as file:
                    script_content = '\n'.join(
                        line for line in file.readlines() if not line.strip().startswith('#')
                    )
                processed_commands.append(['script', [script_content]])
            except FileNotFoundError:
                processed_commands.append(['command', [sub_command]])
        else:
            processed_commands.append(['command', [sub_command]])

    return [x] + processed_commands


# Global dictionary to map container script paths to repository paths
script_dict = {}


def normalize_path(path):
    """
    Normalize path separators to forward slashes
    
    Args:
        path (str): Path to normalize
        
    Returns:
        str: Normalized path
    """
    return path.replace("\\", "/")


def handle_copy_add(y, x, stage_aliases, current_stage_number, repo_path, dockerfile_path_local):
    """
    Parse COPY/ADD instructions and handle multi-stage dependencies
    
    This function:
    1. Extracts --from parameter for multi-stage builds
    2. Parses source and destination paths
    3. Handles both array and space-separated formats
    4. Maps script files for later extraction
    5. Creates dependency relationships between stages
    
    Args:
        y (str): COPY/ADD instruction value
        x (str): Instruction name ('COPY' or 'ADD')
        stage_aliases (dict): Mapping of stage aliases to stage numbers
        current_stage_number (int): Current build stage number
        repo_path (str): Path to the repository
        dockerfile_path_local (str): Path to the Dockerfile
        
    Returns:
        tuple: (parsed_result, dependency1, dependency2)

    Example:
    y = "COPY --from=builder /app/build /app"
    x = "COPY"
    stage_aliases = {}
    current_stage_number = 0
    repo_path = "/path/to/repo"
    dockerfile_path_local = "/path/to/Dockerfile"
    handle_copy_add(y, x, stage_aliases, current_stage_number, repo_path, dockerfile_path_local) # returns ([0, ['COPY', [['source', ['/app/build']], ['destination', ['/app']]]]], ['dependency', ['consumer_builder', [(0, 1)]]], ['dependency', ['builder_consumer', [(1, 0)]]])
    """
    pos_from = searchPosition(y, '--from')
    copy_from = []
    dependency1 = []
    dependency2 = []
    if (pos_from != -1):
        pos = searchPosition(y[pos_from:], ' ')
        copy_from = y[pos_from + 7:pos]
        y = y[:pos_from] + y[pos + 1:]
        if copy_from.isdigit():
            dependency_stage_number = int(copy_from)
        else:
            dependency_stage_number = stage_aliases.get(copy_from, None)
        if dependency_stage_number is not None:
            dependency1 = ['dependency', ['consumer_builder', [(current_stage_number, dependency_stage_number)]]]
            dependency2 = ['dependency', ['builder_consumer', [(dependency_stage_number, current_stage_number)]]]

    if (y[0] == '['):
        # Array format: COPY ["src1", "src2"] dest
        if (y[-1] == ']'):
            pos = y.rfind(',')
            src = y[1:pos]
            dest = y[pos + 1:-1]
            dest = dest.strip()
            dest = json.dumps(dest)
            pos2 = dest.rfind('"')
            dest = dest[3:pos2 - 2]
        else:
            pos = y.rfind(' ')
            pos2 = y.rfind(']')
            src = y[1:pos2]
            dest = y[pos2 + 1:]
        files = src.split(',')
        z = "[\"" + x + "\", [\"source\", "
        ok = False
        for file in files:
            file = file.strip()
            if ok:
                z = z + ", "
            f = json.dumps(file)
            pos2 = f.rfind('"')
            z = z + "[\"" + f[3:pos2 - 2] + "\"]"
            ok = True

        z = z + "], [\"destination\", [" + json.dumps(dest) + "]]]"
    else:
        # Space-separated format: COPY src1 src2 dest
        pos = y.rfind(' ')
        src = y[:pos]
        dest = y[pos + 1:]
        files = src.split()
        z = "[\"" + x + "\", [\"source\", "
        ok = False
        for file in files:
            if ok:
                z = z + ", "
            f = json.dumps(file)
            z = z + "[" + f + "]"
            ok = True
        if (pos_from != -1):
            z = z + "], [\"destination\", [" + json.dumps(dest) + "]], [\"from\", [" + json.dumps(copy_from) + "]]]"
        else:
            z = z + "], [\"destination\", [" + json.dumps(dest) + "]]]"
    
    # Map script files for later extraction
    for file in files:
        file = file.strip()
        if file == '.':
            file_path_in_repo = Path(dockerfile_path_local).parent
        else:
            file_path_in_repo = os.path.join(repo_path, file)
        if os.path.isdir(file_path_in_repo):
            for dirpath, dirnames, filenames in os.walk(file_path_in_repo):
                for filename in filenames:
                    if is_script(filename):
                        container_path = (os.path.join(dest, filename)).replace("\\", '/')
                        repo_script_path = os.path.join(dirpath, filename)
                        script_dict[container_path] = repo_script_path.replace("\\", '/')
        elif is_script(file):
            absolute_path_in_container = dest.replace("\\", '/')
            script_dict[absolute_path_in_container] = file_path_in_repo.replace("\\", '/')

    return json.loads(z), dependency1, dependency2


def EAST(x, temp_repo_path, dockerfile_path_local):
    """
    Main EAST parser function
    
    This is the core function that parses a Dockerfile and converts it into
    an enhanced abstract syntax tree. It handles all Dockerfile instructions
    and creates a structured representation that includes:
    - Multi-stage build information
    - Dependencies between stages
    - Script content extraction
    - Environment variables and arguments
    - Port exposures and user specifications
    
    Args:
        x (str): Dockerfile content as string
        temp_repo_path (str): Path to the repository
        dockerfile_path_local (str): Path to the Dockerfile
        
    Returns:
        str: JSON string representation of the EAST

    Example:
    x = "FROM ubuntu:latest\nRUN apt-get update && apt-get install -y curl\nCOPY --from=builder /app/build /app"
    temp_repo_path = "/path/to/repo"
    dockerfile_path_local = "/path/to/Dockerfile"
    EAST(x, temp_repo_path, dockerfile_path_local) # returns [0, ['FROM', ['image_name', ['ubuntu']], ['image_tag', ['latest']]], ['RUN', [['command', ['apt-get update']], ['command', ['apt-get install -y curl']]]], ['COPY', [['source', ['/app/build']], ['destination', ['/app']]]]]
    """
    dfp = DockerfileParser()
    dfp.content = x

    nb_stage = -1
    stage_aliases = {}
    current_stage = []
    stages = ["stage"]
    recorded_dependencies_consumer_builder = set()
    recorded_dependencies_builder_consumer = set()
    
    # Process each instruction in the Dockerfile
    for instr in (dfp.structure):
        if instr['instruction'] == 'FROM':
            # Start a new build stage
            if current_stage:
                stages.append(current_stage)
            nb_stage += 1
            current_stage, stage_alias, stage_name = handle_from(instr['value'], instr['instruction'], nb_stage)

            # Handle dependencies between stages with same base image
            if stage_name in stage_aliases:
                stage_number = stage_aliases[stage_name]
                dependency1 = ['dependency', ['consumer_builder', [(nb_stage, stage_number)]]]
                dependency2 = ['dependency', ['builder_consumer', [(stage_number, nb_stage)]]]
                if dependency1:
                    dependency_key1 = (dependency1[1][1][0][1], dependency1[1][1][0][0])
                    if dependency_key1 not in recorded_dependencies_consumer_builder:
                        current_stage.insert(1, dependency1)
                        recorded_dependencies_consumer_builder.add(dependency_key1)

                if dependency2:
                    dependency_key2 = (dependency2[1][1][0][0], dependency2[1][1][0][1])
                    if dependency_key2 not in recorded_dependencies_builder_consumer:
                        nb_stage_builder = dependency2[1][1][0][0]
                        for s in stages:
                            if isinstance(s, list):
                                if len(s) > 0 and s[0] == nb_stage_builder:
                                    s.insert(1, dependency2)
                                    break

                        recorded_dependencies_builder_consumer.add(dependency_key2)
            if stage_alias:
                stage_aliases[stage_alias] = nb_stage
            continue
        elif (instr['instruction'] == 'ENV'):
            # Handle environment variables
            env_entries = handle_env(instr['value'], instr['instruction'])
            for env_entry in env_entries[1]:
                current_stage.append(['ENV', env_entry[1], env_entry[2]])
            continue
        elif (instr['instruction'] == 'ARG'):
            # Handle build arguments
            if current_stage:
                x = handle_arg(instr['value'], instr['instruction'])
            else:
                current_stage = handle_arg(instr['value'], instr['instruction'])
                stages.append(current_stage)
                current_stage = []
                continue
        elif (instr['instruction'] == 'EXPOSE'):
            # Handle port exposures
            x = handle_expose(instr['value'], instr['instruction'])
        elif instr['instruction'] == 'USER':
            # Handle user specifications
            x = handle_user(instr['value'], instr['instruction'])

        elif (instr['instruction'] == 'RUN'):
            # Handle RUN commands with script detection
            x = handle_run(instr['value'], instr['instruction'])

        elif (instr['instruction'] in {'COPY', 'ADD'}):
            # Handle file copy operations with multi-stage dependencies
            x, dependency1, dependency2 = handle_copy_add(instr['value'], instr['instruction'], stage_aliases, nb_stage,
                                                          temp_repo_path, dockerfile_path_local)
            if dependency1:
                dependency_key1 = (dependency1[1][1][0][1], dependency1[1][1][0][0])
                if dependency_key1 not in recorded_dependencies_consumer_builder:
                    current_stage.insert(1, dependency1)
                    recorded_dependencies_consumer_builder.add(dependency_key1)

            if dependency2:
                dependency_key2 = (dependency2[1][1][0][0], dependency2[1][1][0][1])
                if dependency_key2 not in recorded_dependencies_builder_consumer:
                    nb_stage_builder = dependency2[1][1][0][0]
                    for s in stages:
                        if isinstance(s, list):
                            if len(s) > 0 and s[0] == nb_stage_builder:
                                s.insert(1, dependency2)
                                break

                    recorded_dependencies_builder_consumer.add(dependency_key2)
        elif (instr['instruction'] == 'WORKDIR'):
            # Handle working directory changes
            x = [instr['instruction'], ['path', [instr['value']]]]

        elif (instr['instruction'] == 'ONBUILD'):
            # Handle ONBUILD instructions
            x = [instr['instruction'], ['instruction', [instr['value']]]]
        elif (instr['instruction'] in ['ENTRYPOINT', 'CMD']):
            # Handle entrypoint and command specifications
            x = [instr['instruction'], ['command', [instr['value']]]]
        elif (instr['instruction'] == 'VOLUME'):
            # Handle volume declarations
            x = [instr['instruction'], ['arguments', [instr['value']]]]
        else:
            continue

        if (instr['instruction'] != 'FROM') and (x):
            current_stage.append(x)
        variable = ''

    if current_stage:
        stages.append(current_stage)
    result = json.dumps(stages)
    return result


def create_node(data):
    """
    Recursively create a tree node from structured data
    
    Args:
        data: List or scalar data to convert to node
        
    Returns:
        Node: Tree node representing the data

    Example:
    data = [0, ['FROM', ['image_name', ['ubuntu']], ['image_tag', ['latest']]]]
    create_node(data) # returns Node(0, children=[Node('FROM', children=[Node('image_name', children=[Node('ubuntu')]), Node('image_tag', children=[Node('latest')])])])
    """
    if isinstance(data, list) and len(data) > 0:
        children = [create_node(child) for child in data[1:]]
        return Node(str(data[0]), children=children)
    else:
        return Node(str(data))


def json_to_tree(json_list):
    """
    Convert JSON list representation to a tree structure
    
    Args:
        json_list: JSON list representation of the EAST
        
    Returns:
        Node: Root node of the tree

    Example:
    json_list = [0, ['FROM', ['image_name', ['ubuntu']], ['image_tag', ['latest']]]]
    json_to_tree(json_list) # returns Node(0, children=[Node('FROM', children=[Node('image_name', children=[Node('ubuntu')]), Node('image_tag', children=[Node('latest')])])])
    """
    root = create_node(json_list)
    return root


def get_EAST(dockerfile_content, temp_repo_path, dockerfile_path_local):
    """
    Main entry point for EAST parsing
    
    This function takes Dockerfile content and converts it into a tree structure
    that can be used for analysis, visualization, and dependency tracking.
    
    Args:
        dockerfile_content (str): Raw Dockerfile content
        temp_repo_path (str): Path to the repository containing the Dockerfile
        dockerfile_path_local (str): Path to the Dockerfile within the repository
        
    Returns:
        Node: Root node of the EAST tree

    Example:
    dockerfile_content = "FROM ubuntu:latest\nRUN apt-get update && apt-get install -y curl\nCOPY --from=builder /app/build /app"
    temp_repo_path = "/path/to/repo"
    dockerfile_path_local = "/path/to/Dockerfile"
    get_EAST(dockerfile_content, temp_repo_path, dockerfile_path_local) # returns Node(0, children=[Node('FROM', children=[Node('image_name', children=[Node('ubuntu')]), Node('image_tag', children=[Node('latest')])]), Node('RUN', children=[Node('command', children=[Node('apt-get update')]), Node('command', children=[Node('apt-get install -y curl')])]), Node('COPY', children=[Node('source', children=[Node('/app/build')]), Node('destination', children=[Node('/app')])])])
    """
    json_list = EAST(dockerfile_content, temp_repo_path, dockerfile_path_local)
    json_list = json.loads(json_list)
    tree = json_to_tree(json_list)
    return tree