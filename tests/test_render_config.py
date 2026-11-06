"""deploy/render-config.sh builds the instance's config from SSM; test it with a stub `aws`."""

import os
import secrets
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy" / "render-config.sh"
CONFIG = """HV_DOMAIN=demo.example.org
HERITAGEVOICE_COGNITO_REGION=eu-west-2
HERITAGEVOICE_COGNITO_USER_POOL_ID=eu-west-2_POOL
HERITAGEVOICE_COGNITO_APP_CLIENT_ID=client123
"""
# Random per run, so no secret-shaped literal sits in the repository.
SECRETS = {
    "POSTGRES_PASSWORD": secrets.token_hex(8),
    "HV_COOKIE_SECRET": secrets.token_hex(8),
    "HV_COGNITO_CLIENT_SECRET": secrets.token_hex(8),
}


def run(tmp_path, params):
    """Run the script with a fake `aws` that prints the given SSM parameters."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    lines = "".join(f"/heritagevoice/demo/{k}\t{v}\n" for k, v in params.items())
    fake = bin_dir / "aws"
    fake.write_text(f"#!/usr/bin/env bash\nprintf '%s' '{lines}'\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    chown = bin_dir / "chown"  # records the request; the real one needs root
    chown.write_text(f"#!/usr/bin/env bash\necho \"$@\" >> '{bin_dir}/chown.log'\n")
    chown.chmod(chown.stat().st_mode | stat.S_IEXEC)
    config = tmp_path / "config.env"
    config.write_text(CONFIG)
    out = tmp_path / "out"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HV_CONFIG_DIR": str(out)}
    result = subprocess.run(
        ["bash", str(SCRIPT), "/heritagevoice/demo", str(config)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, out


def test_the_script_writes_the_env_file_and_the_streamlit_secrets(tmp_path):
    result, out = run(tmp_path, SECRETS)
    assert result.returncode == 0, result.stderr
    env = (out / "app.env").read_text()
    assert "HV_DOMAIN=demo.example.org" in env
    assert f"POSTGRES_PASSWORD={SECRETS['POSTGRES_PASSWORD']}" in env
    toml = (out / "secrets.toml").read_text()
    assert 'redirect_uri = "https://demo.example.org/oauth2callback"' in toml
    assert 'expose_tokens = ["access"]' in toml
    assert f'client_secret = "{SECRETS["HV_COGNITO_CLIENT_SECRET"]}"' in toml
    assert "cognito-idp.eu-west-2.amazonaws.com/eu-west-2_POOL/.well-known" in toml


def test_the_streamlit_file_is_chowned_to_the_ui_container_user(tmp_path):
    result, out = run(tmp_path, SECRETS)
    assert result.returncode == 0, result.stderr
    owner, target = (tmp_path / "bin" / "chown.log").read_text().split()
    assert owner == "10001:10001"
    assert target == str(out / "secrets.toml")


def test_the_files_are_private_to_root(tmp_path):
    _, out = run(tmp_path, SECRETS)
    for name in ("app.env", "secrets.toml"):
        assert stat.S_IMODE((out / name).stat().st_mode) == 0o600


@pytest.mark.parametrize("missing", sorted(SECRETS))
def test_a_missing_secret_stops_the_deploy_before_anything_is_written(tmp_path, missing):
    params = {k: v for k, v in SECRETS.items() if k != missing}
    result, out = run(tmp_path, params)
    assert result.returncode != 0
    assert f"Missing setting: {missing}" in result.stderr
    assert not (out / "app.env").exists()


@pytest.mark.parametrize("bad", ['has"quote', "line\\nbreak", "semi;colon", "dollar$sign"])
def test_values_that_could_break_the_toml_or_shell_are_rejected(tmp_path, bad):
    result, out = run(tmp_path, {**SECRETS, "HV_COOKIE_SECRET": bad})
    assert result.returncode != 0
    assert "unsupported characters" in result.stderr
    assert not (out / "secrets.toml").exists()


def test_a_parameter_store_value_replaces_the_same_setting_from_config_env(tmp_path):
    result, out = run(tmp_path, {**SECRETS, "HV_DOMAIN": "new.example.org"})
    assert result.returncode == 0, result.stderr
    lines = (out / "app.env").read_text().splitlines()
    assert [line for line in lines if line.startswith("HV_DOMAIN=")] == [
        "HV_DOMAIN=new.example.org"
    ]
    toml = (out / "secrets.toml").read_text()
    assert 'redirect_uri = "https://new.example.org/oauth2callback"' in toml


def test_every_setting_appears_once_and_config_env_order_is_kept(tmp_path):
    result, out = run(tmp_path, {**SECRETS, "HV_DOMAIN": "new.example.org"})
    assert result.returncode == 0, result.stderr
    names = [line.split("=")[0] for line in (out / "app.env").read_text().splitlines()]
    assert len(names) == len(set(names))
    assert names[0] == "HV_DOMAIN"
