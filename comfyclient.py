# ---
# python comfyclient.py --modal-workspace edenartlab --test-json workspaces/slow_new/workflows/texture_flow/test.json --workflow texture_flow
# ---

import argparse
import json
import pathlib
import sys
import time
import urllib.request

OUTPUT_DIR = pathlib.Path("comfyui_modal_outputs")
OUTPUT_DIR.mkdir(exist_ok=True, parents=True)

def main(args: argparse.Namespace):
    url = f"https://{args.modal_workspace}--newcomfy-{args.workspace_name}-comfyui-api{'-dev' if args.dev else ''}.modal.run/"
    print(f"Running against URL: {url}")

    # Load test parameters from JSON file
    with open(args.test_json, 'r') as f:
        test_params = json.load(f)
    
    # Combine test parameters with workflow
    payload = {
        "workflow": args.workflow,
        "args": test_params
    }
    
    data = json.dumps(payload).encode("utf-8")
    print(f"Running workflow: {args.workflow}")
    print(f"Test parameters: {test_params}")
    print("Waiting for response...")
    start_time = time.time()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as response:
            assert response.status == 200, response.status
            elapsed = round(time.time() - start_time, 1)
            print(f"Image finished generating in {elapsed} seconds!")
            filename = OUTPUT_DIR / f"{args.workflow}_{int(time.time())}.png"
            filename.write_bytes(response.read())
            print(f"Saved to '{filename}'")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"Workflow API not found at {url}")
        else:
            print(f"HTTP Error {e.code}: {e.reason}")


def parse_args(arglist: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--modal-workspace",
        type=str,
        default="edenartlab",
        help="Name of the Modal workspace with the deployed app. Run `modal profile current` to check.",
    )
    parser.add_argument(
        "--test-json",
        type=str,
        default="test.json",
        help="Path to test.json file containing workflow parameters.",
    )
    parser.add_argument(
        "--workspace_name",
        type=str,
        default="slow-new-stage",
        help="Name of the Modal workspace with the deployed app. Run `modal profile current` to check.",
    )
    parser.add_argument(
        "--workflow",
        type=str,
        default="txt2img",
        help="Name of the workflow to run.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="use this flag when running the ComfyUI server in development mode with `modal serve`",
    )

    return parser.parse_args(arglist[1:])


def slugify(s: str) -> str:
    return s.lower().replace(" ", "-").replace(".", "-").replace("/", "-")[:32]


if __name__ == "__main__":
    args = parse_args(sys.argv)
    main(args)
