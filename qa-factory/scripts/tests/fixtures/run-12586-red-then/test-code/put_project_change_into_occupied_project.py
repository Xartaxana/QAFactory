# verbatim copy of test_ms_teams_integration.py lines 314-364 (decorators and the function); here they are lines 2-52, the manifest pins 345-364 of the original
@pytest.mark.integration
@pytest.mark.project_integration
@pytest.mark.testcase("TP1-12586")
@pytest.mark.qa(case="TC-003", then=[1, 2, 3, 4], obligations=["OB-4"], shape="extend")
@pytest.mark.api
def test_put_project_change_into_project_with_ms_teams_is_rejected(
    project_pair,
    ms_teams_integration_factory,
    project_assistant_factory,
    integration_utils,
):
    """TC-003: a PUT moving an MS Teams integration into a project that has one is refused, nothing changes."""
    moving, _ = ms_teams_integration_factory(project_pair.source)
    occupant, _ = ms_teams_integration_factory(project_pair.target)
    moving_before = integration_utils.find_project_integration(
        project_pair.source, moving.id
    )
    target_credentials = ms_teams_credentials(
        project_assistant_factory(project_pair.target).id
    )

    status, body = integration_utils.change_project_status(
        moving, project_pair.target, credential_values=target_credentials
    )
    in_target = integration_utils.list_project_integrations(
        project_pair.target, CredentialTypes.MS_TEAMS
    )
    in_source = integration_utils.list_project_integrations(
        project_pair.source, CredentialTypes.MS_TEAMS
    )

    assert_that(
        status,
        all_of(greater_than_or_equal_to(400), less_than(500)),
        f"Then 1 (P-occupied): a move into a project that already has MS Teams must get 4xx, body: {body}",
    )
    assert_that(
        body,
        is_not(contains_string("Project mismatch")),
        "Then 2: the rejection reason must not be the 'Project mismatch' text.",
    )
    assert_that(
        [row.id for row in in_target],
        contains_exactly(occupant.id),
        "Then 3: the target must still hold exactly one MS Teams integration, its original id.",
    )
    assert_that(
        [row.model_dump() for row in in_source],
        contains_exactly(moving_before.model_dump()),
        "Then 4: the source must still hold its own MS Teams integration, unchanged.",
    )
