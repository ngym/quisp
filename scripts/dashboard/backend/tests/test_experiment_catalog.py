from __future__ import annotations

from scripts.dashboard.backend.app.experiment_catalog import resolve_experiment_request, schema_for
from scripts.dashboard.backend.app.models import SimRunStartRequest


def test_schema_for_profile_returns_structured_fields():
    schema = schema_for(
        template_id="quisp/simulations/two_nodes.ini",
        config_name="two_node_MIM",
    )

    assert schema.profile_id == "verify_two_node_setup"
    assert any(item.id == "traffic.request_rate_hz" for item in schema.parameter_definitions)
    assert "setup_success_ratio" in schema.recommended_metric_ids


def test_verification_profile_resolves_to_tuned_defaults():
    request = SimRunStartRequest(
        experiment_profile_id="verify_two_node_setup",
    )

    resolved = resolve_experiment_request(request)
    request_dict = resolved["request_dict"]

    assert request_dict["template_id"] == "quisp/simulations/two_nodes.ini"
    assert request_dict["config_name"] == "two_node_MIM"
    assert request_dict["sim_time_limit"] == 4.0
    assert request_dict["overrides"]["**.physical_backend_type"] == "graph_state"
    assert request_dict["overrides"]["*.source.is_initiator"] == "true"
    assert request_dict["requested_metrics"] == [
        "request_submitted_count",
        "request_setup_success_count",
        "setup_success_ratio",
        "setup_latency_s",
    ]


def test_qutip_verification_profile_defaults_to_qutip_backend():
    request = SimRunStartRequest(
        experiment_profile_id="verify_qutip_backend",
    )

    resolved = resolve_experiment_request(request)
    request_dict = resolved["request_dict"]

    assert request_dict["template_id"] == "quisp/simulations/two_nodes.ini"
    assert request_dict["config_name"] == "two_node_MIM"
    assert request_dict["sim_time_limit"] == 4.0
    assert request_dict["overrides"]["**.physical_backend_type"] == "qutip_density_matrix"
    assert request_dict["overrides"]["*.source.app.request_generation_interval"] == "2s"


def test_replay_timeline_verification_profile_defaults_to_early_event_timeline():
    request = SimRunStartRequest(
        experiment_profile_id="verify_replay_timeline",
    )

    resolved = resolve_experiment_request(request)
    request_dict = resolved["request_dict"]

    assert request_dict["template_id"] == "quisp/simulations/two_nodes.ini"
    assert request_dict["config_name"] == "two_node_MIM"
    assert request_dict["sim_time_limit"] == 10.0
    assert request_dict["overrides"]["**.physical_backend_type"] == "graph_state"
    assert request_dict["overrides"]["*.source.app.request_generation_interval"] == "0.5s"
    assert request_dict["overrides"]["*.source.is_initiator"] == "true"


def test_resolve_experiment_request_merges_defaults_and_raw_overrides():
    request = SimRunStartRequest(
        experiment_profile_id="two_node_mim_smoke",
        parameter_values={
            "traffic.request_rate_hz": 5,
            "execution.sim_time_limit_s": 4,
        },
        overrides={
            "*.source.is_initiator": "false",
            "*.source.app.request_generation_interval": "0.5s",
        },
    )

    resolved = resolve_experiment_request(request)
    request_dict = resolved["request_dict"]

    assert request_dict["template_id"] == "quisp/simulations/two_nodes.ini"
    assert request_dict["config_name"] == "two_node_MIM"
    assert request_dict["sim_time_limit"] == 4.0
    assert request_dict["experiment_profile_id"] == "two_node_mim_smoke"
    assert request_dict["requested_metrics"] == [
        "setup_success_ratio",
        "setup_latency_s",
        "bellpair_generation_rate_per_s",
        "photon_loss_rate_per_s",
    ]
    assert request_dict["overrides"]["*.source.is_initiator"] == "false"
    assert request_dict["overrides"]["*.source.app.request_generation_interval"] == "0.5s"


def test_schema_for_unsupported_config_returns_execution_fallback():
    schema = schema_for(
        template_id="unknown.ini",
        config_name="General",
    )

    assert schema.profile_id is None
    assert [item.id for item in schema.parameter_definitions] == [
        "execution.seed_set",
        "execution.sim_time_limit_s",
        "execution.backend_type",
    ]
