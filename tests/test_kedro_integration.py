"""End-to-end `kedro run` through DeepYAMLConfigLoader (CONFIG_LOADER_CLASS).

Builds a minimal-but-real Kedro project in a temp directory and runs it with
KedroSession, asserting that every framework behavior that depends on config
loading works: loader instantiation via CONFIG_LOADER_CLASS/CONFIG_LOADER_ARGS,
catalog construction with resolved interpolations, credentials resolution and
injection (including oc.env), parameters and runtime params reaching nodes,
and the framework's tolerance of missing optional config files.

Not a scale test; bench/ covers performance.
"""

from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest

kedro = pytest.importorskip("kedro")

from kedro.framework.session import KedroSession  # noqa: E402
from kedro.framework.startup import bootstrap_project  # noqa: E402

DATASETS_PY = """\
from kedro.io import AbstractDataset


class ProbeDataset(AbstractDataset):
    \"\"\"Records what the framework passes to it; stores data in memory.\"\"\"

    instances = []
    store = {}

    def __init__(self, filepath, credentials=None):
        self.filepath = filepath
        self.credentials = credentials
        ProbeDataset.instances.append(self)

    def _load(self):
        return ProbeDataset.store[self.filepath]

    def _save(self, data):
        ProbeDataset.store[self.filepath] = data

    def _describe(self):
        return {"filepath": self.filepath}
"""

SETTINGS_PY = """\
from deepyaml.kedro import DeepYAMLConfigLoader

CONFIG_LOADER_CLASS = DeepYAMLConfigLoader
CONFIG_LOADER_ARGS = {"base_env": "base", "default_run_env": "local"}
"""


def write(root: Path, relative_path: str, text: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


def make_project(root: Path, package: str, conf: dict[str, str], nodes_py: str) -> Path:
    write(
        root,
        "pyproject.toml",
        f"""\
        [tool.kedro]
        package_name = "{package}"
        project_name = "{package}"
        kedro_init_version = "{kedro.__version__}"
        """,
    )
    write(root, f"src/{package}/__init__.py", "")
    write(root, f"src/{package}/settings.py", SETTINGS_PY)
    write(root, f"src/{package}/datasets.py", DATASETS_PY)
    write(root, f"src/{package}/pipeline_registry.py", nodes_py)
    (root / "conf" / "local").mkdir(parents=True, exist_ok=True)
    for relative_path, text in conf.items():
        write(root, f"conf/{relative_path}", text)
    return root


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    """A project exercising globals, credentials (oc.env), and runtime params."""
    return make_project(
        tmp_path_factory.mktemp("proj"),
        package="dyproj",
        conf={
            "base/globals.yml": "folder: data\nkind: dyproj.datasets.ProbeDataset\n",
            "base/catalog.yml": (
                "probed:\n"
                "  type: ${globals:kind}\n"
                "  filepath: ${globals:folder}/probe.txt\n"
                "  credentials: db\n"
            ),
            "base/parameters.yml": (
                "model_options:\n  seed: ${runtime_params:seed,3}\n  factor: 10\n"
            ),
            "local/credentials.yml": (
                "db:\n  user: ${oc.env:DYPROJ_USER,guest}\n  token: s3cr3t\n"
            ),
        },
        nodes_py="""\
        from kedro.pipeline import node, pipeline


        def emit():
            return "payload"


        def combine(probed, model_options):
            return {"probed": probed, **model_options}


        def register_pipelines():
            return {
                "__default__": pipeline(
                    [
                        node(emit, None, "probed"),
                        node(combine, ["probed", "params:model_options"], "result"),
                    ]
                )
            }
        """,
    )


@pytest.fixture(autouse=True)
def _no_telemetry(monkeypatch):
    monkeypatch.setenv("KEDRO_DISABLE_TELEMETRY", "true")


def run_session(project_path: Path, **kwargs):
    bootstrap_project(project_path)
    with KedroSession.create(project_path, **kwargs) as session:
        outputs = session.run()
    # Free outputs come back as MemoryDatasets in Kedro >= 1.0.
    return {
        name: value.load() if hasattr(value, "load") else value
        for name, value in outputs.items()
    }


def probe_dataset(package: str):
    return importlib.import_module(f"{package}.datasets").ProbeDataset


def test_kedro_run_end_to_end(project, monkeypatch):
    monkeypatch.delenv("DYPROJ_USER", raising=False)
    outputs = run_session(project)

    # Parameters (with the runtime_params default) flowed into the node.
    assert outputs["result"] == {"probed": "payload", "seed": 3, "factor": 10}

    # The catalog entry was built with resolved ${globals:...} interpolations
    # (Kedro absolutizes relative filepaths against the project root), and
    # credentials were loaded (oc.env default) and injected by name.
    probe = probe_dataset("dyproj").instances[-1]
    assert Path(probe.filepath) == project / "data" / "probe.txt"
    assert probe.credentials == {"user": "guest", "token": "s3cr3t"}


def test_credentials_read_environment_variables(project, monkeypatch):
    monkeypatch.setenv("DYPROJ_USER", "admin")
    run_session(project)
    assert probe_dataset("dyproj").instances[-1].credentials["user"] == "admin"


def test_runtime_params_reach_parameters_and_resolver(project):
    outputs = run_session(
        project, runtime_params={"seed": 99, "model_options": {"factor": 20}}
    )
    # seed via the ${runtime_params:...} resolver, factor via the deep merge.
    assert outputs["result"] == {"probed": "payload", "seed": 99, "factor": 20}


@pytest.mark.filterwarnings("ignore:Parameters not found")
def test_missing_optional_config_is_tolerated(tmp_path_factory):
    """No credentials.yml and no parameters: the framework catches the
    MissingConfigException our adapter raises, and the run still succeeds."""
    project_path = make_project(
        tmp_path_factory.mktemp("bare"),
        package="dyproj_bare",
        conf={"base/catalog.yml": "# no datasets; output stays in memory\n"},
        nodes_py="""\
        from kedro.pipeline import node, pipeline


        def emit():
            return 42


        def register_pipelines():
            return {"__default__": pipeline([node(emit, None, "result")])}
        """,
    )
    outputs = run_session(project_path)
    assert outputs["result"] == 42
