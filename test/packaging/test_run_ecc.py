from pathlib import Path


def test_packaged_entrypoint_has_a_single_ecc_cli():
    project_root = Path(__file__).parents[2]
    source = (project_root / "packaging" / "run_ecc.py").read_text()

    assert "ecc-agent-rpc" not in source
    assert "agent.rpc_server" not in source
    assert "from chipcompiler.cli.main import main as entrypoint" in source
    assert "raise SystemExit(main())" in source
