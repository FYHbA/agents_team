from app.config import get_settings
from app.models.dto import WorkflowPlanRequest
from app.services.workflows import build_workflow_plan


def test_workflow_plan_contains_core_roles() -> None:
    request = WorkflowPlanRequest(task="Debug the failing API route and add regression checks.")
    response = build_workflow_plan(request, get_settings())

    roles = {agent.role for agent in response.agents}
    assert "planner" in roles
    assert "coder" in roles
    assert "reviewer" in roles
    assert response.command_policy == "dangerous-commands-confirmed"
    assert response.outputs
