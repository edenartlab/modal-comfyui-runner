# 1. Deploy ComfyUI behind a web endpoint:
# WORKSPACE=slow_new modal deploy modal_comfy.py

import json
import subprocess
import uuid
import os
from pathlib import Path
from typing import Dict

import modal
from deploy_utils import *
import deploy_constants as cfg 

# Get workspace configuration from environment
workspace_name = os.getenv("WORKSPACE")
workflows = os.getenv("WORKFLOWS", "")
db = os.getenv("DB", "STAGE").upper()

if not workspace_name:
    raise Exception("WORKSPACE environment variable is required")

print("========================================")
print(f"db: {db}")
print(f"workspace: {workspace_name}")
if workflows:
    print(f"Specific workflows: {workflows}")
print("========================================")

vol = modal.Volume.from_name(f"newcomfy-data-volume", create_if_missing=True)


def download_files_from_workspace():
    """Download files specified in downloads.json for the current workspace."""
    downloads_file = "/root/workspace/downloads.json"
    comfy_root_dir = os.environ.get("COMFYUI_PATH", "/root/comfy/ComfyUI")
    
    print(f"Downloading files from {downloads_file}")

    with open(downloads_file, 'r') as f:
        downloads = json.load(f)
    
    for path_key, source_identifier in downloads.items():
        comfy_path = Path(comfy_root_dir) / path_key
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
    
    vol.commit()
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
        
    vol.commit()
    return

image = (  # build up a Modal Image
    modal.Image.debian_slim(python_version="3.11")
    .env({"COMFYUI_PATH": cfg.root_comfy_dir})
    .env({"WORKSPACE": workspace_name})
    .env({"WORKFLOWS": workflows})

    .apt_install("git", "wget")
    .pip_install("httpx", "tqdm")
    .pip_install("fastapi[standard]==0.115.4")  # install web dependencies
    .pip_install("comfy-cli==1.3.9")  # install comfy-cli
    .run_commands(  # use comfy-cli to install ComfyUI and its dependencies
        "comfy --workspace=/root/ComfyUI --skip-prompt install --fast-deps --nvidia --version 0.3.10"
    )
    # Copy local files:
    .add_local_dir(
        local_path=Path(__file__).parent / "memory_snapshot_helper",
        remote_path=f"{cfg.root_comfy_dir}/custom_nodes/memory_snapshot_helper",
        copy=True,
    )
    .add_local_dir(
        local_path=Path(__file__).parent / "workspaces" / workspace_name,
        remote_path="/root/workspace",
        copy=True,
    )
    # Add all .py files in the current directory to the image
    .add_local_dir(
        local_path=Path(__file__).parent,
        remote_path="/root/",
        copy=True,
        ignore=["memory_snapshot_helper"],
    )
    .run_function(
        download_files_from_workspace,
        volumes={"/data": vol}
    )
    .run_function(
        install_custom_nodes_from_snapshot,
        volumes={"/data": vol}
    )   
    .run_function(print_directory_structure,
        volumes={"/data": vol}
    )
)


app_name = f"newcomfy-{workspace_name}-{db.lower()}"
app = modal.App(name=app_name, image=image)

# ## Running ComfyUI interactively
# Spin up an interactive ComfyUI server by wrapping the `comfy launch` command in a Modal Function
# and serving it as a [web server](https://modal.com/docs/guide/webhooks#non-asgi-web-servers).

@app.function( # Stateless / serve
    max_containers=1,  # limit interactive session to 1 container
    gpu=cfg.interactive_GPU,  # defined in deploy_constants.py
    volumes={"/data": vol},  # mounts our cached models
)
@modal.concurrent(
    max_inputs=cfg.max_inputs
)
@modal.web_server(8000, startup_timeout=cfg.startup_timeout)
def ui():
    subprocess.Popen("comfy launch -- --listen 0.0.0.0 --port 8000", shell=True)

# At this point you can run `modal serve comfyapp.py` and open the UI in your browser for the classic ComfyUI experience.

# Remember to **close your UI tab** when you are done developing.
# This will close the connection with the container serving ComfyUI and you will stop being charged.


########################################################
# ## Running ComfyUI as an API
########################################################
# To run a workflow as an API:
# 1. Stand up a "headless" ComfyUI server in the background when the app starts.
# 2. Define an `infer` method that takes in a workflow path and runs the workflow on the ComfyUI server.
# 3. Create a web handler `api` as a web endpoint, so that we can run our workflow as a service and accept inputs from clients.
# We group all these steps into a single Modal `cls` object, which we'll call `ComfyUI`.

@app.cls( # Stateful / deploy
    scaledown_window=cfg.scaledown_window,
    gpu=cfg.deploy_GPU,
    cpu=cfg.n_cpus,
    max_containers=cfg.max_containers,
    min_containers=cfg.min_containers,
    timeout=cfg.comfyui_timeout,
    volumes={"/data": vol},
    enable_memory_snapshot=True,  # snapshot container state for faster cold starts
)
@modal.concurrent(max_inputs=cfg.max_inputs)
class ComfyUI:
    port: int = 8000

    @modal.enter(snap=True)
    def launch_comfy_background(self):
        cmd = f"comfy launch --background -- --port {self.port}"
        subprocess.run(cmd, shell=True, check=True)

    @modal.enter(snap=False)
    def restore_snapshot(self):
        # initialize GPU for ComfyUI after snapshot restore
        # note: requires patching core ComfyUI, see the memory_snapshot_helper directory for more details
        import requests

        response = requests.post(f"http://127.0.0.1:{self.port}/cuda/set_device")
        if response.status_code != 200:
            print("Failed to set CUDA device")
        else:
            print("Successfully set CUDA device")

    @modal.method()
    def infer(self, workflow_path):
        # sometimes the ComfyUI server stops responding (we think because of memory leaks), so this makes sure it's still up
        self.poll_server_health()

        # runs the comfy run --workflow command as a subprocess
        cmd = f"comfy run --workflow {workflow_path} --wait --timeout {cfg.comfyui_timeout} --verbose"
        subprocess.run(cmd, shell=True, check=True)

        # completed workflows write output images to this directory
        output_dir = f"{cfg.root_comfy_dir}/output"

        # Grab the latest file in the output directory:
        latest_file = max(Path(output_dir).iterdir(), key=lambda x: x.stat().st_mtime)

        # returns the output file as bytes
        return latest_file.read_bytes()

    @modal.fastapi_endpoint(method="POST")
    def api(self, data: Dict):
        from fastapi import Response

        # Support workflow selection through request
        workflow_name = data.get("workflow")
        
        workflow_path = f"/root/workspace/workflows/{workflow_name}/workflow_api.json"
        workflow_data = json.loads(Path(workflow_path).read_text())
        workflow_data = inject_args_into_workflow(workflow_data, data.get("args"))
        # save this updated workflow to a new file
        new_workflow_file = f"{uuid.uuid4().hex}.json"
        json.dump(workflow_data, Path(new_workflow_file).open("w"))
        
        print(f"Running workflow: {workflow_name} with args: {data.get('args')}")

        # run inference on the currently running container
        content_bytes = self.infer.local(new_workflow_file)

        return Response(content_bytes, media_type="image/png")

    def poll_server_health(self) -> Dict:
        import socket
        import urllib

        try:
            # check if the server is up (response should be immediate)
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/system_stats")
            urllib.request.urlopen(req, timeout=5)
            print("ComfyUI server is healthy")
        except (socket.timeout, urllib.error.URLError) as e:
            # if no response in 5 seconds, stop the container
            print(f"Server health check failed: {str(e)}")
            modal.experimental.stop_fetching_inputs()

            # all queued inputs will be marked "Failed", so you need to catch these errors in your client and then retry
            raise Exception("ComfyUI server is not healthy, stopping container")


# ## More resources
# - [Alternative approach](https://modal.com/blog/comfyui-mem-snapshots) for deploying ComfyUI with memory snapshots
# - Run a ComfyUI workflow as a [Python script](https://modal.com/blog/comfyui-prototype-to-production)