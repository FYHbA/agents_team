from __future__ import annotations

from pathlib import Path

from app.models.dto import WorkflowRunCreateRequest
from app.services.workflow_runs import create_workflow_run, get_workflow_run, list_workflow_runs


def test_workflow_run_is_persisted_and_listed(test_settings, tmp_path: Path) -> None:
    project_path = tmp_path / "repo"
    project_path.mkdir()

    record = create_workflow_run(
        WorkflowRunCreateRequest(
            task="Implement the first workflow run persistence layer and verify the saved outputs.",
            project_path=str(project_path),
        ),
        test_settings,
    )

    run_path = Path(record.run_path)
    assert run_path.exists()
    assert (run_path / "run.json").exists()
    assert Path(record.report_path).exists()
    assert Path(record.changes_path).exists()

    listed = list_workflow_runs(str(project_path), test_settings)
    assert listed
    assert listed[0].id == record.id

    loaded = get_workflow_run(record.id, str(project_path), test_settings)
    assert loaded.id == record.id
    assert loaded.git_strategy == "manual"
