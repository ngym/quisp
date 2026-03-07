from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional

from .experiment_models import ExperimentFormSchema, ExperimentParameterDefinition, ExperimentParameterOption, ExperimentProfile


def _enum(label: str, value: str) -> ExperimentParameterOption:
    return ExperimentParameterOption(label=label, value=value)


PARAMETER_DEFINITIONS: dict[str, ExperimentParameterDefinition] = {
    "execution.seed_set": ExperimentParameterDefinition(id="execution.seed_set", label="Seed Set", group="execution", type="int", minimum=0, maximum=999999999, step=1, help_text="再現性のための乱数シードです。"),
    "execution.sim_time_limit_s": ExperimentParameterDefinition(id="execution.sim_time_limit_s", label="Sim Time Limit", group="execution", type="float", unit="s", minimum=0, step=0.1, help_text="OMNeT++ の sim-time-limit です。"),
    "execution.backend_type": ExperimentParameterDefinition(
        id="execution.backend_type",
        label="Backend",
        group="execution",
        type="enum",
        enum_options=[
            _enum("Error Basis", "error_basis"),
            _enum("Graph State", "graph_state"),
            _enum("QuTiP Density Matrix", "qutip_density_matrix"),
            _enum("QuTiP State Vector", "qutip_state_vector"),
        ],
        help_text="physical_backend_type を切り替えます。",
    ),
    "traffic.request_rate_hz": ExperimentParameterDefinition(id="traffic.request_rate_hz", label="Request Rate", group="traffic", type="float", unit="Hz", minimum=0.001, step=0.1, help_text="1/interval で request_generation_interval に変換します。"),
    "traffic.pairs_per_request": ExperimentParameterDefinition(id="traffic.pairs_per_request", label="Pairs Per Request", group="traffic", type="int", minimum=1, step=1),
    "traffic.src_node_ids": ExperimentParameterDefinition(id="traffic.src_node_ids", label="Source Nodes", group="traffic", type="multi_select", advanced=True, help_text="未実装 profile では表示されません。"),
    "traffic.dst_node_ids": ExperimentParameterDefinition(id="traffic.dst_node_ids", label="Destination Nodes", group="traffic", type="multi_select", advanced=True, help_text="未実装 profile では表示されません。"),
    "traffic.concurrency": ExperimentParameterDefinition(id="traffic.concurrency", label="Concurrency", group="traffic", type="int", minimum=1, step=1, advanced=True),
    "traffic.required_fidelity": ExperimentParameterDefinition(id="traffic.required_fidelity", label="Required Fidelity", group="traffic", type="float", minimum=0.0, maximum=1.0, step=0.01, advanced=True),
    "physical.link_distance_km": ExperimentParameterDefinition(id="physical.link_distance_km", label="Link Distance", group="physical", type="float", unit="km", minimum=0.0, step=1.0, advanced=True),
    "physical.emission_success_probability": ExperimentParameterDefinition(id="physical.emission_success_probability", label="Emission Success Prob.", group="physical", type="float", minimum=0.0, maximum=1.0, step=0.01),
    "physical.memory_lifetime_s": ExperimentParameterDefinition(id="physical.memory_lifetime_s", label="Memory Lifetime", group="physical", type="float", unit="s", minimum=0.0, step=0.1, advanced=True),
    "physical.gate_error_rate": ExperimentParameterDefinition(id="physical.gate_error_rate", label="Gate Error Rate", group="physical", type="float", minimum=0.0, maximum=1.0, step=0.0001, advanced=True),
    "physical.measurement_error_rate": ExperimentParameterDefinition(id="physical.measurement_error_rate", label="Measurement Error Rate", group="physical", type="float", minimum=0.0, maximum=1.0, step=0.0001, advanced=True),
    "protocol.purification_type": ExperimentParameterDefinition(id="protocol.purification_type", label="Purification", group="protocol", type="string", advanced=True),
    "protocol.threshold_fidelity": ExperimentParameterDefinition(id="protocol.threshold_fidelity", label="Threshold Fidelity", group="protocol", type="float", minimum=0.0, maximum=1.0, step=0.01, advanced=True),
    "protocol.retry_timeout_s": ExperimentParameterDefinition(id="protocol.retry_timeout_s", label="Retry Timeout", group="protocol", type="float", unit="s", minimum=0.0, step=0.1, advanced=True),
    "resource.buffer_size": ExperimentParameterDefinition(id="resource.buffer_size", label="Buffer Size", group="resource", type="int", minimum=1, step=1, advanced=True),
}


PROFILE_REGISTRY: dict[str, ExperimentProfile] = {
    "verify_two_node_setup": ExperimentProfile(
        profile_id="verify_two_node_setup",
        label="Verify: two-node setup",
        description="Simulator 起動、request/setup、Results タブの要点を最短で確認するための 2 node 検証プロファイルです。",
        template_id="quisp/simulations/two_nodes.ini",
        config_name="two_node_MIM",
        supported_parameter_ids=[
            "execution.seed_set",
            "execution.sim_time_limit_s",
            "execution.backend_type",
            "traffic.request_rate_hz",
            "traffic.pairs_per_request",
        ],
        default_parameter_values={
            "execution.sim_time_limit_s": 4.0,
            "execution.backend_type": "graph_state",
            "traffic.request_rate_hz": 1.0,
            "traffic.pairs_per_request": 1,
        },
        recommended_metric_ids=[
            "request_submitted_count",
            "request_setup_success_count",
            "setup_success_ratio",
            "setup_latency_s",
        ],
        override_mappings={
            "execution.backend_type": {"kind": "direct", "override_key": "**.physical_backend_type"},
            "traffic.request_rate_hz": {"kind": "inverse_rate_to_interval_s", "override_key": "*.source.app.request_generation_interval"},
            "traffic.pairs_per_request": {"kind": "direct", "override_key": "*.source.app.number_of_bellpair"},
        },
        fixed_overrides={
            "*.source.is_initiator": "true",
        },
        notes="最初に使う確認用プロファイルです。launch, sim completion, summary artifact, Results の基本線を短時間で確認できます。",
    ),
    "verify_replay_timeline": ExperimentProfile(
        profile_id="verify_replay_timeline",
        label="Verify: replay timeline",
        description="Replay の time seek、cluster 進行、sim 時間同期を確認するための 2 node 検証プロファイルです。",
        template_id="quisp/simulations/two_nodes.ini",
        config_name="two_node_MIM",
        supported_parameter_ids=[
            "execution.seed_set",
            "execution.sim_time_limit_s",
            "execution.backend_type",
            "traffic.request_rate_hz",
            "traffic.pairs_per_request",
        ],
        default_parameter_values={
            "execution.sim_time_limit_s": 10.0,
            "execution.backend_type": "graph_state",
            "traffic.request_rate_hz": 2.0,
            "traffic.pairs_per_request": 1,
        },
        recommended_metric_ids=[
            "request_submitted_count",
            "request_setup_success_count",
            "setup_success_ratio",
            "setup_latency_s",
        ],
        override_mappings={
            "execution.backend_type": {"kind": "direct", "override_key": "**.physical_backend_type"},
            "traffic.request_rate_hz": {"kind": "inverse_rate_to_interval_s", "override_key": "*.source.app.request_generation_interval"},
            "traffic.pairs_per_request": {"kind": "direct", "override_key": "*.source.app.number_of_bellpair"},
        },
        fixed_overrides={
            "*.source.is_initiator": "true",
        },
        notes="t=0 付近から replayable event が出るように調整した Replay 検証用プロファイルです。Results よりも time seek と cluster 表示の確認に向きます。",
    ),
    "verify_qutip_backend": ExperimentProfile(
        profile_id="verify_qutip_backend",
        label="Verify: qutip backend",
        description="repo-local QuTiP 環境と qutip backend の起動経路を確認するための 2 node 検証プロファイルです。",
        template_id="quisp/simulations/two_nodes.ini",
        config_name="two_node_MIM",
        supported_parameter_ids=[
            "execution.seed_set",
            "execution.sim_time_limit_s",
            "execution.backend_type",
            "traffic.request_rate_hz",
            "traffic.pairs_per_request",
        ],
        default_parameter_values={
            "execution.sim_time_limit_s": 4.0,
            "execution.backend_type": "qutip_density_matrix",
            "traffic.request_rate_hz": 0.5,
            "traffic.pairs_per_request": 1,
        },
        recommended_metric_ids=[
            "request_submitted_count",
            "request_setup_success_count",
            "setup_success_ratio",
            "failure_reason_breakdown",
        ],
        override_mappings={
            "execution.backend_type": {"kind": "direct", "override_key": "**.physical_backend_type"},
            "traffic.request_rate_hz": {"kind": "inverse_rate_to_interval_s", "override_key": "*.source.app.request_generation_interval"},
            "traffic.pairs_per_request": {"kind": "direct", "override_key": "*.source.app.number_of_bellpair"},
        },
        fixed_overrides={
            "*.source.is_initiator": "true",
        },
        notes="QuTiP 依存と backend wiring の確認用です。高速 GUI 確認ではなく、qutip backend が import failure なしで完走することを優先します。",
    ),
    "verify_linear_five_activity": ExperimentProfile(
        profile_id="verify_linear_five_activity",
        label="Verify: five-node activity",
        description="5 node line topology で Monitor / Replay / Results をまとめて確認するための activity 検証プロファイルです。",
        template_id="quisp/networks/omnetpp.ini",
        config_name="EntanglementSwapping_Linear_FIVE_MM_Test",
        supported_parameter_ids=[
            "execution.seed_set",
            "execution.sim_time_limit_s",
            "execution.backend_type",
            "physical.emission_success_probability",
            "protocol.purification_type",
            "protocol.threshold_fidelity",
        ],
        default_parameter_values={
            "execution.sim_time_limit_s": 12.0,
            "execution.backend_type": "graph_state",
            "physical.emission_success_probability": 1.0,
        },
        recommended_metric_ids=[
            "bellpair_generated_count",
            "bellpair_generation_rate_per_s",
            "bellpair_inventory_peak",
            "photon_loss_rate_per_s",
        ],
        override_mappings={
            "execution.backend_type": {"kind": "direct", "override_key": "**.physical_backend_type"},
            "physical.emission_success_probability": {"kind": "direct", "override_key": "**.emission_success_probability"},
            "protocol.purification_type": {"kind": "direct", "override_key": "**.purification_type"},
            "protocol.threshold_fidelity": {"kind": "direct", "override_key": "**.threshold_fidelity"},
        },
        notes="GUI 確認用の既定プロファイルです。1-2-3-4-5 の topology、bellpair activity、key moments、Replay の動きをまとめて確認できます。",
    ),
    "two_node_mim_smoke": ExperimentProfile(
        profile_id="two_node_mim_smoke",
        label="Two-node MIM smoke",
        description="最小の 2 node MIM 実験。setup と request cadence の確認向けです。",
        template_id="quisp/simulations/two_nodes.ini",
        config_name="two_node_MIM",
        supported_parameter_ids=[
            "execution.seed_set",
            "execution.sim_time_limit_s",
            "execution.backend_type",
            "traffic.request_rate_hz",
            "traffic.pairs_per_request",
        ],
        default_parameter_values={
            "execution.sim_time_limit_s": 2.0,
            "traffic.request_rate_hz": 1.0,
            "traffic.pairs_per_request": 1,
        },
        recommended_metric_ids=[
            "setup_success_ratio",
            "setup_latency_s",
            "bellpair_generation_rate_per_s",
            "photon_loss_rate_per_s",
        ],
        override_mappings={
            "execution.backend_type": {"kind": "direct", "override_key": "**.physical_backend_type"},
            "traffic.request_rate_hz": {"kind": "inverse_rate_to_interval_s", "override_key": "*.source.app.request_generation_interval"},
            "traffic.pairs_per_request": {"kind": "direct", "override_key": "*.source.app.number_of_bellpair"},
        },
        fixed_overrides={
            "*.source.is_initiator": "true",
        },
        notes="request_generation_interval は request_rate_hz から自動変換されます。",
    ),
    "linear_five_mm_entanglement_swapping": ExperimentProfile(
        profile_id="linear_five_mm_entanglement_swapping",
        label="Linear five-node swapping",
        description="5 node MM topology で entanglement swapping を観測するプロファイルです。",
        template_id="quisp/networks/omnetpp.ini",
        config_name="EntanglementSwapping_Linear_FIVE_MM_Test",
        supported_parameter_ids=[
            "execution.seed_set",
            "execution.sim_time_limit_s",
            "execution.backend_type",
            "physical.emission_success_probability",
            "protocol.purification_type",
            "protocol.threshold_fidelity",
        ],
        default_parameter_values={
            "execution.sim_time_limit_s": 12.0,
            "execution.backend_type": "graph_state",
            "physical.emission_success_probability": 1.0,
        },
        recommended_metric_ids=[
            "bellpair_generation_rate_per_s",
            "bellpair_inventory_peak",
            "photon_loss_rate_per_s",
            "failure_reason_breakdown",
        ],
        override_mappings={
            "execution.backend_type": {"kind": "direct", "override_key": "**.physical_backend_type"},
            "physical.emission_success_probability": {"kind": "direct", "override_key": "**.emission_success_probability"},
            "protocol.purification_type": {"kind": "direct", "override_key": "**.purification_type"},
            "protocol.threshold_fidelity": {"kind": "direct", "override_key": "**.threshold_fidelity"},
        },
        notes="この config は既定では application request を発行しないため setup 系 metric は空になりやすく、interactive 用の既定 backend は graph_state にしています。QuTiP backend も選択可能ですが大幅に遅くなります。",
    ),
    "measurement7000_simple_mim": ExperimentProfile(
        profile_id="measurement7000_simple_mim",
        label="Measurement7000 simple MIM",
        description="大規模 simple MIM 構成を比較するためのプロファイルです。",
        template_id="quisp/networks/omnetpp.ini",
        config_name="Measurement7000_Layer2_Simple_MIM_MM_50km_XPuriri_memErr",
        supported_parameter_ids=[
            "execution.seed_set",
            "execution.sim_time_limit_s",
            "execution.backend_type",
            "physical.emission_success_probability",
            "protocol.purification_type",
        ],
        default_parameter_values={
            "execution.backend_type": "qutip_density_matrix",
            "physical.emission_success_probability": 0.2254,
        },
        recommended_metric_ids=[
            "setup_success_ratio",
            "setup_latency_s",
            "bellpair_generation_rate_per_s",
            "photon_loss_rate_per_s",
            "failure_reason_breakdown",
        ],
        override_mappings={
            "execution.backend_type": {"kind": "direct", "override_key": "**.physical_backend_type"},
            "physical.emission_success_probability": {"kind": "direct", "override_key": "**.emission_success_probability"},
            "protocol.purification_type": {"kind": "direct", "override_key": "**.purification_type"},
        },
    ),
}


def list_profiles() -> list[ExperimentProfile]:
    ordered_keys = sorted(
        PROFILE_REGISTRY,
        key=lambda key: (0 if key.startswith("verify_") else 1, PROFILE_REGISTRY[key].label.lower(), key),
    )
    return [PROFILE_REGISTRY[key].model_copy(deep=True) for key in ordered_keys]


def get_profile(profile_id: Optional[str]) -> Optional[ExperimentProfile]:
    if not profile_id:
        return None
    profile = PROFILE_REGISTRY.get(str(profile_id))
    return profile.model_copy(deep=True) if profile else None


def match_profile(template_id: Optional[str], config_name: Optional[str]) -> Optional[ExperimentProfile]:
    if not template_id or not config_name:
        return None
    for profile in PROFILE_REGISTRY.values():
        if profile.template_id == template_id and profile.config_name == config_name:
            return profile.model_copy(deep=True)
    return None


def schema_for(template_id: str, config_name: str, profile_id: Optional[str] = None) -> ExperimentFormSchema:
    profile = get_profile(profile_id) or match_profile(template_id, config_name)
    if profile is None:
        fallback_ids = ["execution.seed_set", "execution.sim_time_limit_s", "execution.backend_type"]
        return ExperimentFormSchema(
            template_id=template_id,
            config_name=config_name,
            profile_id=None,
            parameter_definitions=[PARAMETER_DEFINITIONS[param_id].model_copy(deep=True) for param_id in fallback_ids],
            default_parameter_values={},
            recommended_metric_ids=["setup_success_ratio", "bellpair_generation_rate_per_s", "photon_loss_rate_per_s"],
            legacy_override_supported=True,
        )
    return ExperimentFormSchema(
        template_id=profile.template_id,
        config_name=profile.config_name,
        profile_id=profile.profile_id,
        parameter_definitions=[PARAMETER_DEFINITIONS[param_id].model_copy(deep=True) for param_id in profile.supported_parameter_ids if param_id in PARAMETER_DEFINITIONS],
        default_parameter_values=deepcopy(profile.default_parameter_values),
        recommended_metric_ids=list(profile.recommended_metric_ids),
        legacy_override_supported=True,
    )


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _convert_mapping(kind: str, value: Any, unit: Optional[str] = None) -> str:
    if kind == "direct":
        return _stringify(value)
    if kind == "identity_bool":
        return "true" if bool(value) else "false"
    if kind == "identity_enum":
        return _stringify(value)
    if kind == "identity_number_with_unit":
        suffix = unit or ""
        return f"{value}{suffix}"
    if kind == "inverse_rate_to_interval_s":
        numeric = float(value)
        if numeric <= 0:
            raise ValueError("request_rate_hz must be positive")
        return f"{1.0 / numeric:.6g}s"
    raise ValueError(f"unsupported override mapping kind: {kind}")


def resolve_experiment_request(request: Any) -> Dict[str, Any]:
    profile = get_profile(getattr(request, "experiment_profile_id", None))
    template_id = getattr(request, "template_id", None)
    config_name = getattr(request, "config_name", None)

    if profile is not None:
      # kept intentionally aligned with profile selection; explicit mismatch is rejected
        if template_id and template_id != profile.template_id:
            raise ValueError("template_id does not match experiment_profile_id")
        if config_name and config_name != profile.config_name:
            raise ValueError("config_name does not match experiment_profile_id")
        template_id = profile.template_id
        config_name = profile.config_name
    elif template_id and config_name:
        profile = match_profile(template_id, config_name)

    if not template_id or not config_name:
        raise ValueError("template_id/config_name or experiment_profile_id is required")

    raw_parameter_values = dict(getattr(request, "parameter_values", {}) or {})
    profile_defaults = deepcopy(profile.default_parameter_values) if profile else {}
    merged_parameter_values = {**profile_defaults, **raw_parameter_values}
    explicit_overrides = {str(key): str(value) for key, value in dict(getattr(request, "overrides", {}) or {}).items()}
    resolved_overrides = deepcopy(profile.fixed_overrides) if profile else {}

    for param_id, value in merged_parameter_values.items():
        if profile is None:
            continue
        mapping = profile.override_mappings.get(param_id)
        if not mapping:
            continue
        resolved_overrides[mapping["override_key"]] = _convert_mapping(mapping["kind"], value, mapping.get("unit"))

    seed_set = getattr(request, "seed_set", None)
    sim_time_limit = getattr(request, "sim_time_limit", None)
    if seed_set is None and "execution.seed_set" in merged_parameter_values:
        seed_set = int(merged_parameter_values["execution.seed_set"])
    if sim_time_limit is None and "execution.sim_time_limit_s" in merged_parameter_values:
        sim_time_limit = float(merged_parameter_values["execution.sim_time_limit_s"])

    resolved_overrides.update(explicit_overrides)
    requested_metrics = list(getattr(request, "requested_metrics", []) or [])
    if not requested_metrics and profile is not None:
        requested_metrics = list(profile.recommended_metric_ids)

    experiment_display_name = getattr(request, "run_name", None) or (profile.label if profile else config_name)

    request_dict = {
        **request.model_dump(),
        "template_id": template_id,
        "config_name": config_name,
        "seed_set": seed_set,
        "sim_time_limit": sim_time_limit,
        "overrides": resolved_overrides,
        "requested_metrics": requested_metrics,
        "parameter_values": merged_parameter_values,
        "experiment_profile_id": profile.profile_id if profile else None,
    }
    return {
        "request_dict": request_dict,
        "profile": profile,
        "resolved_overrides": resolved_overrides,
        "parameter_values": merged_parameter_values,
        "requested_metrics": requested_metrics,
        "experiment_display_name": experiment_display_name,
    }
