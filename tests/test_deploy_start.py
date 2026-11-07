"""deploy/start.sh loads the image CI built, and builds on the server only when none was shipped.

The real script runs against stand-ins for `docker` and `aws` that write down what they were asked
to do, so nothing touches a real machine or a real bucket.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
RELEASE = "abc123def456"
STUB = """#!/usr/bin/env bash
echo "{name} $*" >> "$STUB_LOG"
{body}
"""
DOCKER = """case "$1 $2" in
  "image inspect") [[ -n "$STUB_HAVE_IMAGE" ]] ;;
  "load "*|"load") cat >/dev/null; [[ -z "$STUB_LOAD_FAILS" ]] ;;
esac"""
AWS = """case "$1 $2" in
  "s3api head-object") [[ -z "$STUB_NO_SHIPPED_IMAGE" ]] ;;
  "s3 cp") echo image-bytes; [[ -z "$STUB_COPY_FAILS" ]] ;;
esac"""


def stand_ins(bin_dir):
    """`docker` and `aws` commands that only write down what they were asked."""
    bin_dir.mkdir()
    for name, body in (("docker", DOCKER), ("aws", AWS)):
        script = bin_dir / name
        script.write_text(STUB.format(name=name, body=body))
        script.chmod(0o755)
    return bin_dir


@pytest.fixture
def server(tmp_path):
    """A release tree, a config directory and a bin directory of stand-in commands."""
    tree = tmp_path / "tree"
    (tree / "deploy").mkdir(parents=True)
    shutil.copy(DEPLOY / "start.sh", tree / "deploy" / "start.sh")
    (tree / "deploy" / "render-config.sh").write_text("#!/usr/bin/env bash\n")
    (tree / "deploy" / "render-config.sh").chmod(0o755)
    (tree / "RELEASE").write_text(RELEASE)
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.env").write_text("HV_SSM_PATH=/heritagevoice/test\nHV_RELEASES_BUCKET=bkt\n")
    bin_dir = stand_ins(tmp_path / "bin")
    log = tmp_path / "calls.log"
    log.touch()
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HV_CONFIG_DIR": str(config),
        "STUB_LOG": str(log),
    }
    for name in ("STUB_HAVE_IMAGE", "STUB_NO_SHIPPED_IMAGE", "STUB_LOAD_FAILS", "STUB_COPY_FAILS"):
        env.pop(name, None)

    def run(**extra):
        done = subprocess.run(
            ["bash", str(tree / "deploy" / "start.sh")],
            env={**env, **extra},
            capture_output=True,
            text=True,
            check=False,
        )
        return done, log.read_text().splitlines()

    return run


def compose_up(calls):
    return next(c for c in calls if c.startswith("docker compose") and " up " in c)


def test_the_shipped_image_is_loaded_and_nothing_is_built_on_the_server(server):
    done, calls = server()
    assert done.returncode == 0, done.stderr
    assert f"aws s3 cp --only-show-errors s3://bkt/releases/{RELEASE}.image.tar.gz -" in calls
    assert "docker load" in calls
    assert "--no-build" in compose_up(calls)
    assert "--build" not in compose_up(calls).replace("--no-build", "")


def test_an_image_already_on_the_server_is_not_downloaded_again(server):
    done, calls = server(STUB_HAVE_IMAGE="1")
    assert done.returncode == 0, done.stderr
    assert not any(c.startswith("aws") for c in calls)
    assert "--no-build" in compose_up(calls)


def test_a_release_with_no_shipped_image_is_still_built_on_the_server(server):
    """Rolling back to a release made before images were shipped must keep working."""
    done, calls = server(STUB_NO_SHIPPED_IMAGE="1")
    assert done.returncode == 0, done.stderr
    assert "No shipped image; building here" in done.stdout
    assert "docker load" not in calls
    assert compose_up(calls).endswith("up -d --build")


@pytest.mark.parametrize("broken", ["STUB_LOAD_FAILS", "STUB_COPY_FAILS"])
def test_a_damaged_image_stops_the_deploy_instead_of_starting_something_else(server, broken):
    done, calls = server(**{broken: "1"})
    assert done.returncode != 0
    assert not any(c.startswith("docker compose") and " up " in c for c in calls)
