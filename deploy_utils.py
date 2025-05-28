import json
import subprocess
from pathlib import Path
import os, shutil, tempfile, re
import httpx
import pathlib
from tqdm import tqdm

import yaml
import copy
from typing import Dict, Any, Union, List
import json

def print_directory_structure(root_dir='.', n_levels=3, print_hidden_files=False):
    """
    Print directory structure starting from root_dir up to n_levels deep.
    
    Args:
        root_dir (str): Starting directory path (defaults to current directory '.')
        n_levels (int): Maximum depth to traverse (defaults to 2)
        print_hidden_files (bool): Whether to show hidden files and directories (defaults to False)
    """
    print(f"Directory structure for '{os.path.abspath(root_dir)}':")
    
    for root, dirs, files in os.walk(root_dir):
        # Calculate current level relative to root_dir
        level = root.replace(os.path.abspath(root_dir), "").count(os.sep)
        
        # Filter out hidden directories if print_hidden_files is False
        if not print_hidden_files:
            dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        if level < n_levels:
            indent = " " * 4 * level
            print(f"{indent}{os.path.basename(root)}/")
            
            # Print files in current directory
            subindent = " " * 4 * (level + 1)
            for f in files:
                # Skip hidden files if print_hidden_files is False
                if not print_hidden_files and f.startswith('.'):
                    continue
                print(f"{subindent}{f}")
        
        # Prevent recursing deeper than n_levels
        if level >= n_levels - 1:
            dirs.clear()


def install_custom_node_with_retries(comfy_root_dir, url, commit_hash, max_retries=3):
    """Install a custom node from git URL with specific commit hash and retries."""
    repo_name = url.split("/")[-1].replace(".git", "")
    custom_nodes_dir = os.path.join(comfy_root_dir, "custom_nodes")
    node_path = os.path.join(custom_nodes_dir, repo_name)
    os.chdir("/root")
    
    for attempt in range(max_retries):
        try:
            if os.path.exists(node_path):
                print(f"Removing existing directory: {node_path}")
                subprocess.run(["rm", "-rf", node_path], check=True)
            
            # Clone the repository
            print(f"Cloning {url} (attempt {attempt + 1}/{max_retries})")
            subprocess.run(["git", "clone", url, node_path], check=True)
            
            # Checkout specific commit
            print(f"Checking out commit {commit_hash}")
            subprocess.run(["git", "checkout", commit_hash], cwd=node_path, check=True)
            
            print(f"Successfully installed {repo_name} at commit {commit_hash}")
            return
            
        except subprocess.CalledProcessError as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                print(f"Failed to install {repo_name} after {max_retries} attempts")
                raise

def pprint(obj):
    print(json.dumps(obj, indent=4))

def _url_to_filename(url):
    filename = url.split("/")[-1]
    filename = re.sub(r"\?.*$", "", filename)
    max_length = 255
    if len(filename) > max_length:  # ensure filename is not too long
        name, ext = os.path.splitext(filename)
        filename = name[: max_length - len(ext)] + ext
    return filename

def download_file(url, local_filepath, overwrite=False):
    """
    Download a file from a URL to a local filepath.

    Args:
        url: URL to download from
        local_filepath: Local path to save the file to
        overwrite: Whether to overwrite existing files

    Returns:
        str: Path to the downloaded file
    """
    local_filepath = pathlib.Path(local_filepath)
    local_filepath.parent.mkdir(parents=True, exist_ok=True)

    if local_filepath.exists() and not overwrite:
        print(f"File {local_filepath} already exists. Skipping download.")
        return str(local_filepath)
    else:
        print(f"Downloading file from {url} to {local_filepath}")

    # For CloudFront or standard HTTP requests:
    with httpx.stream("GET", url, follow_redirects=True) as response:
        if response.status_code == 404:
            raise FileNotFoundError(f"No file found at {url}")
        if response.status_code != 200:
            raise Exception(
                f"Failed to download from {url}. Status code: {response.status_code}"
            )

        # Get content length if available
        total = int(response.headers.get("Content-Length", "0"))

        if total == 0:
            # If Content-Length not provided, read all at once
            content = response.read()
            with open(local_filepath, "wb") as f:
                f.write(content)
        else:
            # Stream with progress bar if Content-Length available
            with (
                open(local_filepath, "wb") as f,
                tqdm(
                    total=total, unit_scale=True, unit_divisor=1024, unit="B"
                ) as progress,
            ):
                num_bytes_downloaded = response.num_bytes_downloaded
                for data in response.iter_bytes():
                    f.write(data)
                    progress.update(
                        response.num_bytes_downloaded - num_bytes_downloaded
                    )
                    num_bytes_downloaded = response.num_bytes_downloaded

    return str(local_filepath)

def inject_args_into_workflow(workflow, args):

    print("===== Injecting comfyui args into workflow =====")
    pprint(args)

    # TODO: make this dynamic
    api_yaml_path = "/root/workspace/workflows/txt2img/api.yaml"

    # Download images:
    local_filepaths = []
    for url in args["images"]:
        local_filepath = download_file(url, f"/root/input/{_url_to_filename(url)}")
        local_filepaths.append(local_filepath)

    # TODO make this dynamic    
    args["images"] = local_filepaths

    # Load the api.yaml configuration
    with open(api_yaml_path, 'r') as f:
        api_config = yaml.safe_load(f)
    
    # Create a deep copy of the workflow to avoid modifying the original
    updated_workflow = copy.deepcopy(workflow)
    
    # Get the parameters section from api.yaml
    parameters = api_config.get('parameters', {})
    
    # Process each parameter from test.json
    for param_name, param_value in args.items():
        if param_name not in parameters:
            print(f"Warning: Parameter '{param_name}' not found in api.yaml parameters")
            continue
            
        param_config = parameters[param_name]
        comfyui_config = param_config.get('comfyui', {})
        
        if not comfyui_config:
            print(f"Warning: No comfyui configuration found for parameter '{param_name}'")
            continue
            
        # Extract mapping information
        node_id = comfyui_config.get('node_id')
        field = comfyui_config.get('field', 'inputs')
        subfield = comfyui_config.get('subfield')
        preprocessing = comfyui_config.get('preprocessing')
        remap_configs = comfyui_config.get('remap', [])
        
        if node_id is None or subfield is None:
            print(f"Warning: Missing node_id or subfield for parameter '{param_name}'")
            continue
            
        # Convert node_id to string (ComfyUI workflows use string keys)
        node_id_str = str(node_id)
        
        # Ensure the node exists in the workflow
        if node_id_str not in updated_workflow:
            print(f"Warning: Node {node_id_str} not found in workflow for parameter '{param_name}'")
            continue
            
        # Ensure the field exists in the node
        if field not in updated_workflow[node_id_str]:
            updated_workflow[node_id_str][field] = {}
            
        # Handle preprocessing (e.g., for image arrays that need folder structure)
        processed_value = param_value
        if preprocessing == 'folder' and isinstance(param_value, list):
            # For image arrays, ComfyUI might expect a specific folder structure
            # This is a placeholder - you might need to adjust based on your specific needs
            processed_value = param_value
            
        # Set the main parameter value
        updated_workflow[node_id_str][field][subfield] = processed_value
        
        # Handle remap configurations
        for remap_config in remap_configs:
            remap_node_id = str(remap_config.get('node_id'))
            remap_field = remap_config.get('field', 'inputs')
            remap_subfield = remap_config.get('subfield')
            remap_map = remap_config.get('map', {})
            
            if remap_node_id and remap_subfield and param_value in remap_map:
                # Ensure the remap node exists
                if remap_node_id not in updated_workflow:
                    print(f"Warning: Remap node {remap_node_id} not found in workflow")
                    continue
                    
                # Ensure the remap field exists
                if remap_field not in updated_workflow[remap_node_id]:
                    updated_workflow[remap_node_id][remap_field] = {}
                    
                # Set the remapped value
                mapped_value = remap_map[param_value]
                updated_workflow[remap_node_id][remap_field][remap_subfield] = mapped_value
                
        print(f"Mapped '{param_name}' = {param_value} to node {node_id_str}.{field}.{subfield}")

    return updated_workflow



# TODO: deprecate this ugly hack to avoid verbose logging
def set_debug_mode_to_false(comfy_root_dir):
    """Set DEBUG_MODE to False in ControlFlowUtils helper.py."""
    try:
        helper_path = os.path.join(comfy_root_dir, "custom_nodes/ControlFlowUtils/helper.py")
        with open(helper_path, "r") as f:
            content = f.read()

        if "DEBUG_MODE = True" in content:
            print("Setting DEBUG_MODE to False in ControlFlowUtils helper.py")
            content = content.replace("DEBUG_MODE = True", "DEBUG_MODE = False")
            with open(helper_path, "w") as f:
                f.write(content)
        else:
            pass
    except:
        pass