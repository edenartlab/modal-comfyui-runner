import json
import subprocess
from pathlib import Path
import os
import os

def print_directory_structure(root_dir='.', n_levels=4):
    """
    Print directory structure starting from root_dir up to n_levels deep.
    
    Args:
        root_dir (str): Starting directory path (defaults to current directory '.')
        n_levels (int): Maximum depth to traverse (defaults to 4)
    """
    print(f"Directory structure for '{os.path.abspath(root_dir)}':")
    
    for root, dirs, files in os.walk(root_dir):
        # Calculate current level relative to root_dir
        level = root.replace(os.path.abspath(root_dir), "").count(os.sep)
        
        if level < n_levels:
            indent = " " * 4 * level
            print(f"{indent}{os.path.basename(root)}/")
            
            # Print files in current directory
            subindent = " " * 4 * (level + 1)
            for f in files:
                print(f"{subindent}{f}")
        
        # Prevent recursing deeper than n_levels
        if level >= n_levels - 1:
            dirs.clear()

# Helper functions for workspace support
def download_files_from_workspace():
    """Download files specified in downloads.json for the current workspace."""
    downloads_file = "/root/workspace/downloads.json"
    
    print(f"Downloading files from {downloads_file}")

    with open(downloads_file, 'r') as f:
        downloads = json.load(f)
    
    for path_key, source_identifier in downloads.items():
        comfy_path = Path("/root") / path_key
        vol_path = Path("/data") / path_key
        
        # Skip if file already exists in volume OR if symlink already exists
        if vol_path.exists() or comfy_path.exists():
            if vol_path.exists() and not comfy_path.exists():
                # File exists in volume but symlink is missing - create symlink
                print(f"File exists in volume at {vol_path}, creating missing symlink at {comfy_path}")
                try:
                    comfy_path.parent.mkdir(parents=True, exist_ok=True)
                    is_directory = vol_path.is_dir()
                    comfy_path.symlink_to(vol_path, target_is_directory=is_directory)
                except Exception as e:
                    print(f"Error creating symlink: {e}")
            else:
                print(f"Skipping {comfy_path}, already exists")
            continue
            
        try:
            is_git_clone = source_identifier.startswith("git clone ")
            actual_source_url = source_identifier[10:].strip() if is_git_clone else source_identifier
            
            if is_git_clone:
                print(f"Cloning {actual_source_url} to {vol_path}")
                vol_path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["git", "clone", actual_source_url, str(vol_path)], check=True)
                # Create symlink
                comfy_path.parent.mkdir(parents=True, exist_ok=True)
                comfy_path.symlink_to(vol_path, target_is_directory=True)
            else:
                print(f"Downloading {actual_source_url} to {vol_path}")
                vol_path.parent.mkdir(parents=True, exist_ok=True)
                subprocess.run(["wget", "-O", str(vol_path), actual_source_url], check=True)
                # Create symlink
                comfy_path.parent.mkdir(parents=True, exist_ok=True)
                comfy_path.symlink_to(vol_path)
                
        except Exception as e:
            print(f"Error processing {path_key}: {e}")
            raise
            
    return


def install_custom_nodes_from_snapshot(use_comfy_cli=False):
    """Install custom nodes specified in snapshot.json for the current workspace."""
    snapshot_file = "/root/workspace/snapshot.json"
    comfy_root_dir = os.environ.get("COMFYUI_PATH")

    os.chdir("/root")
    with open(snapshot_file, 'r') as f:
        snapshot = json.load(f)
    
    if use_comfy_cli:
        # Install git custom nodes using comfy-cli
        git_custom_nodes = snapshot.get("git_custom_nodes", {})
        for repo_url, node_info in git_custom_nodes.items():
            if node_info.get("disabled", False):
                print(f"Skipping disabled node: {repo_url}")
                continue
                
            # Extract repo name from URL
            repo_name = repo_url.split("/")[-1].replace(".git", "")
            print(f"Installing custom node: {repo_name} from {repo_url}")
            
            try:
                subprocess.run([
                    "comfy", "node", "install", "--fast-deps", f"{repo_name}@latest"
                ], check=True, cwd="/root")
            except subprocess.CalledProcessError as e:
                print(f"Failed to install {repo_name}: {e}")
                continue

    else:
        """Install custom nodes from snapshot.json with git commit hashes."""
        custom_nodes = snapshot["git_custom_nodes"]
        for url, node in custom_nodes.items():
            print(f"Installing custom node {url} with hash {node['hash']}")
            install_custom_node_with_retries(comfy_root_dir, url, node["hash"])
        
        post_install_commands = snapshot.get("post_install_commands", [])
        for cmd in post_install_commands:
            os.system(cmd)

        set_debug_mode_to_false(comfy_root_dir)

    return


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