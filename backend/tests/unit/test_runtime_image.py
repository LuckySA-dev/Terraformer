from pathlib import Path


def test_runtime_image_installs_openssh_client() -> None:
    dockerfile = (Path(__file__).parents[2] / "Dockerfile").read_text(encoding="utf-8")
    runtime_stage = dockerfile.split("AS runtime", maxsplit=1)[1]

    assert "openssh-client" in runtime_stage
    assert "--no-install-recommends" in runtime_stage
    assert "rm -rf /var/lib/apt/lists/*" in runtime_stage
